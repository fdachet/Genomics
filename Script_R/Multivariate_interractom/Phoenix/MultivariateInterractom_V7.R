#  Date start at 1 not 0
# Put everything upletters
# Input.tabtxt OR InputForValidation.tabtxt
# REMOVE THE NAs before Input???
# Option to keep results across patients only if they are close to each others in a locked time mode

# Data needs to not have redundant and no special characters in  


# 1) After results use Profils need average of average (1 average intra patient then avera interpatients)
# 2) Separate Negative from Positive correlation by adding column 'Type of correlation' positive or negative
# 3) create column CountOfDays 
# 4) create a fused columne patient_PAirofcorrelation_typeofCorrelation for intrapatient
# 5)  PivotPlot create columns  average correlation, average of days, remove columns correlation and days
# 6) Remove duplicates
# 7) Delete PAtients and fused columns

# 8) create a fused columne PAirofcorrelation_typeofCorrelation for inter_patient analyzis
# 9) PivotPlot create columns  'AverageOfAverage' for average correlation, average of days. Also use the count to create column 'quantityOfPatientsPerPairOfCorrelation
#10) Remove duplicates
#11) Remove columns patients and column Fused

#12) Compute pvalue coulumn in function of days and ABS correl     P==T.DIST.2T(|COR|*SQRT(N-2)/SQRT(1-|COR|^2),N-2)      Correct les "#DIV/0!"

#13) Separate column 'pair of correlation on _Vs_ then Reorder columns for DATA1 Interraction Data2 ...
#
#
#
#
#




#columns: 1"PATIENT", 2"SCORE_NAME", 3"SCORE_VALUE", 4"SCORE_UNIT", 5"DATE", 6"DATA_TYPE"
#The Score_Name=  COLOR is used to give a color (score_Value) to patients
#Last Column: The Data_type QUALITATIF_NOTEMPOREL  is used for non temporel and qualitatif data , Score_Name = Color, EpilepticStatus
#Last Column: The data_type EMPTYTO0  correspond a une donne quantitative that will fill to 0 for any number missing in case of 2 scenario: 
    # (1) if there a patient with data,  0 is  filled before the first medication taken 
    #(2) if there is no data, 0 is filled everywhere 

# Need to include NO Temporal Data:  Diagnostic , Epileptic status, medication taken vs no medication, procedures

# Put a score on correlation results based on Epileptic Status (e.g. identification of the correlations enriched in function of Epilepsy)
    # in the data_type "Qualitatif_NoTemporel" the data EPILEPTICSTATUS identify the amount of Epilepsy among Epileptic patients (From 1: Epilepsy, to 4: No Epilepsy), more the score is low and more thewre is Epilepsy (Probably to reverse this in the near futur). 01EPILEPSY, 02PROBABLE,EPILEPSY, 03POSSIBLE EPILEPSY, 04NO EPILEPSY.
    # IdentifyEpilepsyBias needs 1 for epilepsys and 4 for non epilepsy

# "If a pattern is found is repeated in an other windows, the patient is artificially readded in the weight to give more epileptic weight to show that the pair is really correlated ..."

#Interpolations used are linear (average between 2 points), Spline (exemple a plasti deformable rule, try to follow the curves using each sides of the missing data, Stineman: try to correct the exess of the spline interpolation by reducing the splines predicted in case of monotonic series)

# if value=EmptyTo0: in the data_type "Qualitatif_NoTemporel" when type of data need the missing value filled to 0 (e.g. medication), patients information is not filled just the data then value is noted 'EmptyTo0'



rm(list = ls(all = TRUE))


#region#blue libraries 
library(FactoMineR)
library(gtools)
library(fdrtool)
library(audio)
library(Hmisc)
library(matrixStats)
library(ff)
library(propagate)
library(HiClimR)
library(reshape2)
library(plyr)
library(dplyr)
library(stringr)
library(gplots)
library(NMF)
library(imputeTS)


#endregion#

#region#green Parameters
setwd("P:\\Biostat\\Multivariate\\October\\relaxed\\Mitch_ALL")
MinimumProfilLength <- 5
MinimumQuantityOfPatientsPerProfil <- 5
Correl_Thresold <- 0.7    # min5 cor0.9 pvalue=0.04     | min7 cor0.75  pvalue=0.05
DateOrigine <- "2000-1-1"
DateFormat <- FALSE # if dateformat is true transform the date after DateOrigine, else keeps numerical: 1,2,3,4
TimeBining <- 1 # Quantity of days to average to create a data point (default = 1)
TimeWindow <- 5 # The quantity of days that the algorithm will use to search correlations inside
TimeShift <- 0 # Quantity of day(s) that the script is allowed to shift to find the best correlation  pblm: perd cette duree en jours lors du calcul du profil de corelation  (default = 0)
pValue_Thresold <- 1e-2 # Not used yet
ActivateKendall <- FALSE # Not used yet
DataNormalization <- FALSE
Nom_Interraction <- "Validation"
InterractionsMAXExportable <- 500000 # Not used yet
CreateValidationData <- FALSE     #if True need InputForValidation.tabtxt in the wide format (with time as the first row), this create the correct file to be used in excel to creat the final Input.tabtxt (Then put the Epileptic variable for each patient using "Qualitatif_NoTemporel" and the data EPILEPTICSTATUS ) 
SameDayAnalyzis_B = FALSE       # Activate research of correlation around the same day across patients, put DateFormat as FALSE and DataNormalization as TRUE  (default = FALSE)
SameDayDelta = 5     # Not used yet       #only result that have a Delta day spread across the same type of corelation across patients 
PlotOriginalData = FALSE  #Plot each analyze in function of patients
ExportPatientLabels = FALSE  #Add the information about the name of the patient associated with each results
ScoreInFunctionOfEpilepsy_B = TRUE     #KEEPS ON TRUE !!!!
EMPTYTO0_B= TRUE # Activate le remplissage de 0 pour les valeurs non presentent
IdentifyEpilepsyBias = FALSE  #EN COURS (#KEEPS ON FALSE for now) Normalize automaticaly then cancel correlation analyzis do multiple statisteic on univariate epilepsy following epileptic code
Code_Non_Epilepsy<-4      #The control non epilepsy have the code 4
Code_Epilepsy<-1     #The epilepsy patients have the code 1
PngX= 2000      ;   PngY=3000
Interpolation_maxgap_inDays <- 5 # the missing measurement will be interpoled inside this maximum of missing days
Color_Ramp <- colorRampPalette(c("blue","cyan","white","pink", "red"))   #Pour la heatmap     
SizeHeatmapRows <- 1  #Taille de la police pour les rows
SizeHeatmapDays <- 3   #Taille de la police pour les jours





#endregion#





#region#yellow VariablesInternals 
par(xpd=NA)
options(stringsAsFactors = FALSE)
Profils_export_L <- list()
Input_L <- list();temp_L_msd<-list()
Profils_export_Array <- data.frame()
options(stringsAsFactors = FALSE)
if (IdentifyEpilepsyBias) {DataNormalization = TRUE;MinimumProfilLength <- 1;MinimumQuantityOfPatientsPerProfil <- 1 }
#endregion#




#region#purple Critical R 
critical.r <- function(n, alpha = pValue_Thresold) {
        df <- (n - 2)
        critical.t <- qt(alpha / 2, df, lower.tail = FALSE)
        critical.r <- sqrt((critical.t^2) / ((critical.t^2) + df))
        return(critical.r)}
#endregion#      
#region#cyan Function1 

Function1 <- function(    Input_Raw   , TimeBining, TimeShift, MinimumProfilLength, MinimumQuantityOfPatientsPerProfil, DateOrigine, Correl_Thresold,window) {
    # CREATE THE INPUT EN LIST , 1 objet pour chaque patient
    temp_Profils_export_L<-list()
    Patients_L <- levels(as.factor(Input_Raw[, 1]))
    Patients_Q <- length(Patients_L)
    Time_delta <- max(Input_Raw[, 4]) - min(Input_Raw[, 4])
if (Time_delta<MinimumProfilLength){return()}
    Time_min <- min(Input_Raw[, 4])
    Correl_Thresold_Patients <- critical.r(  Patients_Q, pValue_Thresold)    #Not  used yet!!
    for (i in 1:Patients_Q)
    {
     print(paste("Patient",i,"on",Patients_Q,"for Window#",h))
        temp <- which(Input_Raw[, 1] == Patients_L[i])
        Input_L[[i]] <- Input_Raw[temp, ]
        Input_L[[i]] <- Input_L[[i]][, -1]
        Input_L[[i]][, 3] <- as.numeric(Input_L[[i]][, 3])
        temp <- max(Input_L[[i]][, 3])
        temp1 <- array(NA, c(Time_delta+1, length(levels(as.factor(Input_L[[i]][, 1]))) + 1))
        temp1[, 1] <-  Time_min:(Time_min+(Time_delta))
        colnames(temp1) <- c("DATE", levels(as.factor(Input_L[[i]][, 1])))
        temp1 <- as.data.frame(temp1)
        Input_L[[i]] <- cbind(temp1[1], sapply(names(temp1)[-1], function(X) subset(Input_L[[i]], SCORE_NAME == X)$SCORE_VALUE[match(temp1$DATE, subset(Input_L[[i]], SCORE_NAME == X)$DATE)]))
      
    }
     
        #endregion#
        
      #region#cyan function1: TimeShift: ADD COLUMN POUR LES DATES EN DEPHASEES
    if (TimeShift != 0) {
        print("Compute Time Shift")
        TimeShift <- abs(TimeShift)
        for (i in 1:Patients_Q)
        {
             print(paste("Computing Time Shifts for Patient",i,"on",Patients_Q))
            temp <- Input_L[[i]]
            temp1 <- colnames(temp)[-1]
             temp <- as.matrix(temp[, -1])
          
            for (j in 1:TimeShift)
            {
                if (!SameDayAnalyzis_B){colnames(temp) <- paste(temp1, "_Delta+", j, sep = "")}
                temp <- rbind(temp[1, ], temp)
                temp[1, ] <- NA
                Input_L[[i]] <- rbind(Input_L[[i]], Input_L[[i]][1, ])
                Input_L[[i]][dim(Input_L[[i]])[1], ] <- NA
                Input_L[[i]] <- cbind(Input_L[[i]], temp)
                temp2<-dim(Input_L[[i]])[1]            #ADDED  E.C
                Input_L[[i]][temp2,1]<-1+ Input_L[[i]][temp2-1,1]               #ADDED  E.C
            }
        }    }
        
         #endregion#


      #region#cyan function1:  TimeBining: Bin les dates par aglomeration
    if (TimeBining > 1) {
        for (i in 1:Patients_Q)
        {
            print(paste("Binning Dates for Patient",i,"on",Patients_Q))
           temp <- cut(Input_L[[i]][, 1], breaks = seq(from = min(Input_L[[i]][, 1]) - 1, to = max(Input_L[[i]][, 1]), by = TimeBining))
            Input_L[[i]] <- cbind(temp, Input_L[[i]])
            Input_L[[i]] <- aggregate(Input_L[[i]], by = list(Input_L[[i]][, 1]), FUN = mean, na.rm = TRUE)
            Input_L[[i]] <- cbind(ceil(Input_L[[i]][, 3]), Input_L[[i]])
            Input_L[[i]] <- Input_L[[i]][, -c(2:4)]
            colnames(Input_L[[i]])[1] <- "DATE"
        }    }
        names(Input_L) <- Patients_L
        #endregion#

      #region#cyan function1:     # COMPUTE CORRELATIONS, filtre, enleve dates, maximal in case of timeshift dephasage...
    Input_L_Cor <- lapply(Input_L, function(X) {   cor(X, use = "pairwise")    })
        for (i in 1:Patients_Q)
    {
        # FILTRE LES CORRELATIONS , ENLEVE LES NON-RELEVANTES, ENLEVE DATE
         print(paste("Filter Correlations for Patient",i,"on",Patients_Q))
        
       Input_L_Cor[[i]] <- Input_L_Cor[[i]][-1, -1]
       temp<-dim(Input_L_Cor[[i]])[2]
       if (!is.null(temp)&&temp>TimeShift)
       {
       
       
        temp_VariableQ <- (temp) / (TimeShift + 1)
        Input_L_Cor[[i]][lower.tri(Input_L_Cor[[i]], diag = TRUE)] <- NA
        Input_L_Cor[[i]][which(abs(Input_L_Cor[[i]]) < Correl_Thresold)] <- NA
        temp_colnames <- colnames(Input_L_Cor[[i]])
        # TAKE ONLY THE MAXIMAL CORRELATION IN CASE OF MULTIPLE CORRELATION FOR DEPHASAGES
        if (TimeShift != 0) {
            temp_k <- t(kronecker(matrix(1:((1+TimeShift)^2),TimeShift+1,byrow=FALSE),matrix(1,temp_VariableQ,temp_VariableQ)))
            temp <- split(Input_L_Cor[[i]], temp_k)
      #      temp <- array(unlist(temp), c(temp_VariableQ* (TimeShift + 1),temp_VariableQ* (TimeShift + 1), TimeShift + 1))
              temp<-array(unlist(temp),c(temp_VariableQ,temp_VariableQ,(1+TimeShift)^2))
            
            if (dim(temp)[1]>=2)
            {
            for (j in 1:((TimeShift + 1)^2))
            {
                diag(temp[, , j]) <- NA
            }
            }
            temp <- aperm(temp, c(3, 2, 1))
            temp <- apply(temp, c(2, 3), function(Y) {Y[-which.max(abs(Y))] <- NA;Y})
            temp <- aperm(temp, c(3, 2, 1))
     #   temp <- array(temp, c(temp_VariableQ * (TimeShift + 1), temp_VariableQ * (TimeShift + 1))) 
temp<-split(as.numeric(temp),ceiling(seq_along(temp)/temp_VariableQ^2))
temp<-matrix(unsplit(temp,temp_k),c(temp_VariableQ * (TimeShift + 1), temp_VariableQ * (TimeShift + 1)))
        colnames(temp) <- temp_colnames
        rownames(temp) <- temp_colnames
        temp <- round(temp, 2)
        Input_L_Cor[[i]] <- temp    
}
 #endregion#
      #region#cyan function1:  EXPORT LES PROFILES
        temp_notNA <- which(!is.na(Input_L_Cor[[i]]), arr.ind = TRUE)
        for (j in 1:dim(temp_notNA)[1])
        {
            if (length(temp_notNA) != 0) {
                temp1 <- Input_L[[i]][, 1 + temp_notNA[j, 1]]
                temp2 <- Input_L[[i]][, 1 + temp_notNA[j, 2]]
                temp3 <- !is.na(temp1) & !is.na(temp2)
                temp1 <- temp1[temp3]
                temp2 <- temp2[temp3]
                if (length(temp1) >= MinimumProfilLength) {
                    temp3 <- which(temp3)
                    temp_cor <- Input_L_Cor[[i]][temp_notNA[j, 1], temp_notNA[j, 2]]
                    temp <- sort(c(temp_colnames[temp_notNA[j, 1]], temp_colnames[temp_notNA[j, 2]]))
                    temp_pairName <- paste(temp[1], "_Vs_", temp[2], sep = "")
                    temp1 <- c(paste("window=",window,sep=""),Patients_L[i], temp_pairName, temp[1], temp_cor, temp[2], paste(temp_colnames[temp_notNA[j, 1]], "="), temp1)
                    temp2 <- c(paste("window=",window,sep=""),Patients_L[i], temp_pairName, temp[1], temp_cor, temp[2], paste(temp_colnames[temp_notNA[j, 2]], "="), temp2)
if(DateFormat&&!SameDayAnalyzis_B){  temp3 <- c(Patients_L[i], temp_pairName, temp[1], temp_cor, temp[2], "Date=", as.character(as.Date(DateOrigine) + (Time_min +as.numeric(TimeBining * temp3))))}
  if(!DateFormat||SameDayAnalyzis_B){  temp3 <- c(Patients_L[i], temp_pairName, temp[1], temp_cor, temp[2], "Date=",  (Time_min +as.numeric(TimeBining * temp3)-1))  }    

temp3<-c(paste("window=",window,sep=""),temp3)
    
                    temp4 <- rbind(temp3, temp2, temp1)
                    temp_Profils_export_L[[length(temp_Profils_export_L) + 1]] <- temp4
                }
            }
        }
    }
    }
    return(temp_Profils_export_L)
   
}

#endregion#

##############################  START   #############################


print("START")


if (SameDayAnalyzis_B) {  DataNormalization <- TRUE}

#region#black Create ValidationData for testing
if (CreateValidationData){
Input_L_Raw <- read.table("InputForValidation.tabtxt", sep = "\t", header = FALSE, check.names = FALSE)
Input_L_Raw[,1]<-paste(Input_L_Raw[,1],Input_L_Raw[,2],sep="@_@")
rownames(Input_L_Raw)<-Input_L_Raw[,1]
Input_L_Raw<-Input_L_Raw[,-c(1:2)]
Input_L_Raw<-t(Input_L_Raw )
Input_L_Raw<-as.data.frame(Input_L_Raw)
b_m<-melt(Input_L_Raw,id.vars="DATE@_@DATE")
b_m<-b_m[,c(2,2,3,1,1)]
b_m[,4]<-"Unknown"
b_m<-rbind(b_m[1,],b_m)
b_m<-apply(b_m,2,as.character)
b_m[1,]<-c("PATIENT", "SCORE", "SCORE_VALUE", "SCORE_UNIT", "DATE")
b_m[,1]<-sub(pattern="@_@.*",   replacement="",x=b_m[,1])
b_m[,2]<-sub(pattern=".*@_@",   replacement="",x=b_m[,2])
b_m<-cbind(b_m,"DATA_TYPE")




write.table(b_m,file="Input.tabtxt",sep="\t",col.names = FALSE,row.names = FALSE)



stop("***** Validation Data created ******")
}
#endregion#


#region#blue  : Inputation
Input_L_Raw <- read.table("Input.tabtxt", sep = "\t", header = FALSE, check.names = FALSE)
Input_L_Raw<-apply(Input_L_Raw,2,toupper)



# Verify units are all the same for each score_Name, cancel everything if not the same units. Remove Units if they are okay
# LOOSELY IMPLEMENTED
colnames(Input_L_Raw) <- c("PATIENT", "SCORE_NAME", "SCORE_VALUE", "SCORE_UNIT", "DATE","Data Type")
print("Verify Adequation")
print(Input_L_Raw[1, ])
Input_L_Raw <- Input_L_Raw[-1, ]


# Separate Qualitatif from Quantitative
temp<-which(Input_L_Raw[,6]=="QUALITATIF_NOTEMPOREL")
Input_L_Raw_Qualitatif<-Input_L_Raw[temp,]
if (length(temp) !=0) {Input_L_Raw<-Input_L_Raw[-temp,]}
Input_L_Raw_Qualitatif<-as.data.frame(Input_L_Raw_Qualitatif)

#endregion#

Input_L_Raw <- as.data.frame(Input_L_Raw )
Input_L_Raw [,3]<-as.numeric(Input_L_Raw [,3])
Input_L_Raw [,5]<-as.numeric(Input_L_Raw [,5])









#region#lightblue  Remove si pas assez de data points per patients per analyzis
print("Remove si pas assez de data points per patients per analyzis")
Input_L_Raw<-cbind(Input_L_Raw,paste(Input_L_Raw[,1],Input_L_Raw[,2]))
#temp<-add_count(Input_L_Raw,Input_L_Raw[,5])
Input_L_Raw<-as.data.frame(Input_L_Raw)
Input_L_Raw[,3]<-as.numeric(Input_L_Raw[,3])
Input_L_Raw[,5]<-as.numeric(Input_L_Raw[,5])

temp<- ave(Input_L_Raw[,ncol(Input_L_Raw)],Input_L_Raw[,ncol(Input_L_Raw)], FUN=length)

Input_L_Raw<-cbind(Input_L_Raw,temp)
Input_L_Raw[,ncol(Input_L_Raw)]<-as.numeric(Input_L_Raw[,ncol(Input_L_Raw)])
temp<-which(Input_L_Raw[,ncol(Input_L_Raw)]<MinimumProfilLength)

print(paste("Removing",length(temp),"data with less than",MinimumProfilLength,"Points", "from total of",dim(Input_L_Raw)[1] ) )



if(length(temp)!=0){Input_L_Raw<-Input_L_Raw[-temp,]}
Input_L_Raw<-Input_L_Raw[,-ncol(Input_L_Raw<-Input_L_Raw)]
Input_L_Raw<-Input_L_Raw[,-ncol(Input_L_Raw<-Input_L_Raw)]
#endregion#

#region#red Fill the Emptyto0
if(EMPTYTO0_B)
{
temp<-which(Input_L_Raw[,6]=="EMPTYTO0")

if (length(temp)>=1)
{
Input_L_Raw_EmptyTo0_Pts_Analyzes<-Input_L_Raw[temp,]
Patients<-levels(as.factor(Input_L_Raw[,1]))
Input_L_Raw<-Input_L_Raw[-temp,]


Levels_To0<-levels(as.factor(Input_L_Raw_EmptyTo0_Pts_Analyzes[,2]))


for (indice_analyzeTo0 in 1:length(Levels_To0))
{
print(paste("EmptyTo0 for:",Levels_analyzeTo0[indice_analyzeTo0]))



Input_L_Raw_EmptyTo0_Pts_Analyze1<-Input_L_Raw_EmptyTo0_Pts_Analyzes[which(Input_L_Raw_EmptyTo0_Pts_Analyzes[,2]==Levels_analyzeOK[indice_analyzeOK]),]

temp_patientLevelsOK<-levels(as.factor(Input_L_Raw_EmptyTo0_Pts_Analyze1[,1]))



for (indice_patientLevelsOK in 1:length(temp_patientLevelsOK))
{
Input_L_Raw_EmptyTo0_1Pt_Analyze1<-Input_L_Raw_EmptyTo0_Pts_Analyze1[which(Input_L_Raw_EmptyTo0_Pts_Analyze1[,1]==temp_patientLevelsOK[indice_patientLevelsOK]),]   
temp1<-min(Input_L_Raw_EmptyTo0_1Pt_Analyze1[,5])
if(temp1>1)
{



temp3<-bind_rows(replicate(temp1-1, Input_L_Raw_EmptyTo0_1Pt_Analyze1[1,], simplify = FALSE))


temp3[,3]<-0
temp3[,5]<-c(1:(temp1-1))
Input_L_Raw<-rbind(Input_L_Raw, temp3)
}
}
}



temp_MaxDate<-max(Input_L_Raw_EmptyTo0_Pts_Analyzes[,5])
patientLevelsOK<-levels(as.factor(Input_L_Raw_EmptyTo0_Pts_Analyzes[,1]))


patientLevelsNotOK<-Patients [!(Patients %in% patientLevelsOK)]

temp1<-rep(patientLevelsNotOK,each=temp_MaxDate)
temp1<-rep(temp1,each=length(Levels_analyzeOK))
temp2<-rep(Levels_analyzeOK,each=temp_MaxDate)
temp2<-rep(temp2,length(patientLevelsNotOK))


temp3<-rep(0,length(temp1))
temp4<-rep(NA,length(temp1))

temp5<-rep(1:temp_MaxDate,length(patientLevelsNotOK))
temp6<-rep("FILLEDTO0",length(temp1))


temp<-as.data.frame(cbind(temp1,temp2,temp3,temp4,temp5,temp6))
names(temp)<-names(Input_L_Raw )
Input_L_Raw<-rbind(Input_L_Raw, temp)
}
}






#endregion#
#region#blue merge analyze with units, remove unitsInput_L_Raw[,2]<-paste(Input_L_Raw[,2],"_",Input_L_Raw[,4],sep="")
Input_L_Raw <- Input_L_Raw[, -4]




#endregion#



#region#green DataNormalization
        if(DataNormalization)
        {
levels_factors<-levels(as.factor(Input_L_Raw[,2]))
for (Analyze_indice in 1:(length(levels_factors)))
{
    temp<-which(Input_L_Raw[,2]==levels_factors[Analyze_indice])
    temp1<-Input_L_Raw[temp,3]
    temp_sd <- sd(temp1, na.rm = TRUE) 
    temp_average <- mean(temp1, na.rm = TRUE) 
    Input_L_Raw[temp,3] <- (temp1-temp_average )/temp_sd
    
        }
        }
        
      #endregion#



 #region#yellow  Plot original data
 #if (PatientColorsAdded) {PatientsColor<-Input_L_Raw[-1,c(1,6)];Input_L_Raw<-Input_L_Raw[,-6]}
if (PlotOriginalData)
{
    
print("PlotOriginalData")
FactorLevels<-levels(as.factor(Input_L_Raw[,2]))
for (factor_indice in 1:length(FactorLevels))
{

temp1<-Input_L_Raw[which(Input_L_Raw[,2]==FactorLevels[factor_indice]),]      
temp1<-temp1[order(temp1[,1],temp1[,4]),]
temp_Y_min<-min(temp1[,3],na.rm = TRUE)
temp_Y_max<-max(temp1[,3],na.rm = TRUE)
temp_X_min<-min(temp1[,4],na.rm = TRUE)
temp_X_max<-max(temp1[,4],na.rm = TRUE)
temp_dataType<-temp1[1,5]

temp_patientLevels<-levels(as.factor(temp1[,1]))


if (length(temp_patientLevels) < MinimumQuantityOfPatientsPerProfil){next}

png(filename=paste("R_",FactorLevels[factor_indice],".png"),width=1920, height=1080,units="px",)

for (patient_indice in 1:length(temp_patientLevels))
{
print(paste("Plotting of",FactorLevels[factor_indice],"for patient:",temp_patientLevels[patient_indice]))
temp2<-temp1[which(temp1[,1]==temp_patientLevels[patient_indice]),]      

par(new=TRUE)

temp_title<-paste(FactorLevels[factor_indice],"_(",temp_dataType,")_",length(temp_patientLevels),"pts",sep="")
temp_color<-"dark red"
#if (PatientColorsAdded) {temp_color<-temp2[,5]}

plot(x=temp2[,4] ,    y=temp2[,3], main=temp_title, ylim=c(temp_Y_min, ymax=temp_Y_max),xlim=c(temp_X_min, temp_X_max), xlab="Date",ylab="Value" ,type='p',col=temp_color,pch = 19 )

#"Red:Epilepsy, Ora: ProbableEpilepsy, Green: ProbablyNotEpi, Blue: NotEpilepsy"
temp_color<-"blue"
#if (PatientColorsAdded) {temp_color<-temp2[,5]}

par(new=TRUE)
lines(x=temp2[,4] ,    y=temp2[,3], col=temp_color)



}
dev.off()
par(new=FALSE)

}

#if (PatientColorsAdded) {Input_L_Raw<-Input_L_Raw[,-5]}
    #png(filename=paste(temp_pairs_levels[pair_i],".png"),width=1920, height=1080,units="px",)
    #dev.off()
}
Input_L_Raw<-Input_L_Raw[,-ncol(Input_L_Raw)]
#endregion#


#region#blue IdentifyEpilepsyBias
print ("IdentifyEpilepsyBias")
if (IdentifyEpilepsyBias) {
        Score_L <- levels(as.factor(Input_L_Raw[, 2]))
   Score_Q <- length(Score_L)

   temp<-array(NA,c(Score_Q,max(Input_L_Raw[,4])))
   pValue_Array<-temp
      pValueWilcox_Array<-temp
   Medians_Array<-temp
   Averages_Array<-temp
  pValue_Array_InterpoledLinear<-temp
  pValueWilcox_Array_InterpoledLinear<-temp
   Medians_Array_InterpoledLinear<-temp
   Averages_Array_InterpoledLinear<-temp
    pValue_Array_InterpoledSpline<-temp
        pValueWilcox_Array_InterpoledSpline<-temp
   Medians_Array_InterpoledSpline<-temp
   Averages_Array_InterpoledSpline<-temp
    pValue_Array_InterpoledStineman<-temp
        pValueWilcox_Array_InterpoledStineman<-temp
   Medians_Array_InterpoledStineman<-temp
   Averages_Array_InterpoledStineman<-temp

  Input_L_InterpoledLinear<-Input_L
  Input_L_InterpoledSpline<-Input_L
  Input_L_InterpoledStineman<-Input_L

#Transforme de vertical data en horizontal et do pvalue, median, average....
  for (i in 1:Score_Q)
{
     print(paste(Score_L[i],", Score",i,"on",Score_Q))
        temp <- which(Input_L_Raw[,2] == Score_L[i])
        Input_L[[i]] <- Input_L_Raw[temp, ]
        Input_L[[i]] <- Input_L[[i]][, -2]
        Input_L[[i]][, 3] <- as.numeric(Input_L[[i]][, 3])
        temp <- max(Input_L[[i]][, 3])
        temp1 <- array(NA, c(temp, length(levels(as.factor(Input_L[[i]][, 1]))) + 1))
        temp1[, 1] <-  1:temp
        colnames(temp1) <- c("DATE", levels(as.factor(Input_L[[i]][, 1])))
        temp1 <- as.data.frame(temp1)

        Input_L[[i]] <- cbind(temp1[1], sapply(names(temp1)[-1], function(X) subset(Input_L[[i]], PATIENT == X)$SCORE_VALUE[match(temp1$DATE, subset(Input_L[[i]], PATIENT == X)$DATE)]))
       
          Input_L_InterpoledLinear[[i]]<-apply(Input_L[[i]],2,function(X) {   tryCatch ( {na_interpolation(X,maxgap=Interpolation_maxgap_inDays,option="linear")}, error=function(e) {NA} )})
    Input_L_InterpoledSpline[[i]]<-apply(Input_L[[i]],2,function(X) {  tryCatch ( {na_interpolation(X,maxgap=Interpolation_maxgap_inDays,option="spline")}, error=function(e) {NA} )})
    Input_L_InterpoledStineman[[i]]<-apply(Input_L[[i]],2,function(X) { tryCatch ( { na_interpolation(X,maxgap=Interpolation_maxgap_inDays,option="stine")}, error=function(e) {NA} )})


      
Epilepsy_Columns<-c(  Input_L_Raw_Qualitatif[,1][ which(Input_L_Raw_Qualitatif[,3]==Code_Epilepsy)])
Epilepsy_Columns<-which(colnames(Input_L[[i]]) %in% Epilepsy_Columns)
Non_Epilepsy_Columns<-c(Input_L_Raw_Qualitatif[,1][ which(Input_L_Raw_Qualitatif[,3]==Code_Non_Epilepsy)])
Non_Epilepsy_Columns<-which(colnames(Input_L[[i]]) %in% Non_Epilepsy_Columns)



Input_L_InterpoledLinear[[i]]<-as.data.frame(Input_L_InterpoledLinear[[i]])
Input_L_InterpoledSpline[[i]]<-as.data.frame(Input_L_InterpoledSpline[[i]])
Input_L_InterpoledStineman[[i]]<-as.data.frame(Input_L_InterpoledStineman[[i]])




if ((length(Epilepsy_Columns)>=3 ) & (length(Non_Epilepsy_Columns)>=3) )
{
pValue_Array[i,(1:nrow(Input_L[[i]]))]<-  apply(Input_L[[i]],1,function(X)  {      tryCatch (  {t.test(X[Epilepsy_Columns],X[Non_Epilepsy_Columns])$p.value}, error=function(e) {NA}    )   } )
pValueWilcox_Array[i,(1:nrow(Input_L[[i]]))]<-  apply(Input_L[[i]],1,function(X)  {      tryCatch (  {wilcox.test(X[Epilepsy_Columns],X[Non_Epilepsy_Columns])$p.value}, error=function(e) {NA}    )   } )

Medians_Array[i,(1:nrow(Input_L[[i]]))]<-  apply(Input_L[[i]],1,function(X){ median(X[Epilepsy_Columns],na.rm = TRUE) - median(X[Non_Epilepsy_Columns],na.rm = TRUE)})
Averages_Array[i,(1:nrow(Input_L[[i]]))]<-  apply(Input_L[[i]],1,function(X){ mean(X[Epilepsy_Columns],na.rm = TRUE)  - mean(X[Non_Epilepsy_Columns],na.rm = TRUE)}) 

pValue_Array_InterpoledLinear[i,(1:nrow(Input_L_InterpoledLinear[[i]]))]<-  apply(Input_L_InterpoledLinear[[i]],1,function(X)  {      tryCatch (  {t.test(X[Epilepsy_Columns],X[Non_Epilepsy_Columns])$p.value}, error=function(e) {NA}    )   } )
pValueWilcox_Array_InterpoledLinear[i,(1:nrow(Input_L_InterpoledLinear[[i]]))]<-  apply(Input_L_InterpoledLinear[[i]],1,function(X)  {      tryCatch (  {wilcox.test(X[Epilepsy_Columns],X[Non_Epilepsy_Columns])$p.value}, error=function(e) {NA}    )   } )
Medians_Array_InterpoledLinear[i,(1:nrow(Input_L_InterpoledLinear[[i]]))]<-  apply(Input_L_InterpoledLinear[[i]],1,function(X){ median(X[Epilepsy_Columns],na.rm = TRUE) - median(X[Non_Epilepsy_Columns],na.rm = TRUE)})
Averages_Array_InterpoledLinear[i,(1:nrow(Input_L_InterpoledLinear[[i]]))]<-  apply(Input_L_InterpoledLinear[[i]],1,function(X){ mean(X[Epilepsy_Columns],na.rm = TRUE)  - mean(X[Non_Epilepsy_Columns],na.rm = TRUE)}) 


pValue_Array_InterpoledSpline[i,(1:nrow(Input_L_InterpoledSpline[[i]]))]<-  apply(Input_L_InterpoledSpline[[i]],1,function(X)  {      tryCatch (  {t.test(X[Epilepsy_Columns],X[Non_Epilepsy_Columns])$p.value}, error=function(e) {NA}    )   } )
pValueWilcox_Array_InterpoledSpline[i,(1:nrow(Input_L_InterpoledSpline[[i]]))]<-  apply(Input_L_InterpoledSpline[[i]],1,function(X)  {      tryCatch (  {wilcox.test(X[Epilepsy_Columns],X[Non_Epilepsy_Columns])$p.value}, error=function(e) {NA}    )   } )
Medians_Array_InterpoledSpline[i,(1:nrow(Input_L_InterpoledSpline[[i]]))]<-  apply(Input_L_InterpoledSpline[[i]],1,function(X){ median(X[Epilepsy_Columns],na.rm = TRUE) - median(X[Non_Epilepsy_Columns],na.rm = TRUE)})
Averages_Array_InterpoledSpline[i,(1:nrow(Input_L_InterpoledSpline[[i]]))]<-  apply(Input_L_InterpoledSpline[[i]],1,function(X){ mean(X[Epilepsy_Columns],na.rm = TRUE)  - mean(X[Non_Epilepsy_Columns],na.rm = TRUE)}) 


pValue_Array_InterpoledStineman[i,(1:nrow(Input_L_InterpoledStineman[[i]]))]<-  apply(Input_L_InterpoledStineman[[i]],1,function(X)  {      tryCatch (  {t.test(X[Epilepsy_Columns],X[Non_Epilepsy_Columns])$p.value}, error=function(e) {NA}    )   } )
pValueWilcox_Array_InterpoledStineman[i,(1:nrow(Input_L_InterpoledStineman[[i]]))]<-  apply(Input_L_InterpoledStineman[[i]],1,function(X)  {      tryCatch (  {wilcox.test(X[Epilepsy_Columns],X[Non_Epilepsy_Columns])$p.value}, error=function(e) {NA}    )   } )
Medians_Array_InterpoledStineman[i,(1:nrow(Input_L_InterpoledStineman[[i]]))]<-  apply(Input_L_InterpoledStineman[[i]],1,function(X){ median(X[Epilepsy_Columns],na.rm = TRUE) - median(X[Non_Epilepsy_Columns],na.rm = TRUE)})
Averages_Array_InterpoledStineman[i,(1:nrow(Input_L_InterpoledStineman[[i]]))]<-  apply(Input_L_InterpoledStineman[[i]],1,function(X){ mean(X[Epilepsy_Columns],na.rm = TRUE)  - mean(X[Non_Epilepsy_Columns],na.rm = TRUE)}) 






}
}

names(Input_L)<-levels_factors
names(Input_L_InterpoledLinear)<-levels_factors
names(Input_L_InterpoledSpline)<-levels_factors
names(Input_L_InterpoledStineman)<-levels_factors


row.names(pValue_Array)<-levels_factors
row.names(pValueWilcox_Array)<-levels_factors
row.names(Medians_Array)<-levels_factors
row.names(Averages_Array)<-levels_factors
row.names(pValue_Array_InterpoledLinear)<-levels_factors
row.names(pValueWilcox_Array_InterpoledLinear)<-levels_factors
row.names(Medians_Array_InterpoledLinear)<-levels_factors
row.names(Averages_Array_InterpoledLinear)<-levels_factors
row.names(pValue_Array_InterpoledSpline)<-levels_factors
row.names(pValueWilcox_Array_InterpoledSpline)<-levels_factors
row.names(Medians_Array_InterpoledSpline)<-levels_factors
row.names(Averages_Array_InterpoledSpline)<-levels_factors
row.names(pValue_Array_InterpoledStineman)<-levels_factors
row.names(pValueWilcox_Array_InterpoledStineman)<-levels_factors
row.names(Medians_Array_InterpoledStineman)<-levels_factors
row.names(Averages_Array_InterpoledStineman)<-levels_factors


print("Remove measurements without enough Epileptic patients")
temp<-which(apply(pValue_Array, 1 , function (X) { sum(is.na(X))})==dim(pValue_Array)[2])
pValue_Array<-pValue_Array[-temp,]
temp<-which(apply(pValueWilcox_Array, 1 , function (X) { sum(is.na(X))})==dim(pValueWilcox_Array)[2])
pValueWilcox_Array<-pValueWilcox_Array[-temp,]
temp<-which(apply(Medians_Array, 1 , function (X) { sum(is.na(X))})==dim(Medians_Array)[2])
Medians_Array<-Medians_Array[-temp,]
temp<-which(apply(Averages_Array, 1 , function (X) { sum(is.na(X))})==dim(Averages_Array)[2])
Averages_Array<-Averages_Array[-temp,]

temp<-which(apply(pValue_Array_InterpoledLinear, 1 , function (X) { sum(is.na(X))})==dim(pValue_Array_InterpoledLinear)[2])
pValue_Array_InterpoledLinear<-pValue_Array_InterpoledLinear[-temp,]
temp<-which(apply(pValueWilcox_Array_InterpoledLinear, 1 , function (X) { sum(is.na(X))})==dim(pValueWilcox_Array_InterpoledLinear)[2])
pValueWilcox_Array_InterpoledLinear<-pValueWilcox_Array_InterpoledLinear[-temp,]

temp<-which(apply(Medians_Array_InterpoledLinear, 1 , function (X) { sum(is.na(X))})==dim(Medians_Array_InterpoledLinear)[2])
Medians_Array_InterpoledLinear<-Medians_Array_InterpoledLinear[-temp,]
temp<-which(apply(Averages_Array_InterpoledLinear, 1 , function (X) { sum(is.na(X))})==dim(Averages_Array_InterpoledLinear)[2])
Averages_Array_InterpoledLinear<-Averages_Array_InterpoledLinear[-temp,]

temp<-which(apply(pValue_Array_InterpoledSpline, 1 , function (X) { sum(is.na(X))})==dim(pValue_Array_InterpoledSpline)[2])
pValue_Array_InterpoledSpline<-pValue_Array_InterpoledSpline[-temp,]
temp<-which(apply(pValueWilcox_Array_InterpoledSpline, 1 , function (X) { sum(is.na(X))})==dim(pValueWilcox_Array_InterpoledSpline)[2])
pValueWilcox_Array_InterpoledSpline<-pValueWilcox_Array_InterpoledSpline[-temp,]

temp<-which(apply(Medians_Array_InterpoledSpline, 1 , function (X) { sum(is.na(X))})==dim(Medians_Array_InterpoledSpline)[2])
Medians_Array_InterpoledSpline<-Medians_Array_InterpoledSpline[-temp,]
temp<-which(apply(Averages_Array_InterpoledSpline, 1 , function (X) { sum(is.na(X))})==dim(Averages_Array_InterpoledSpline)[2])
Averages_Array_InterpoledSpline<-Averages_Array_InterpoledSpline[-temp,]

temp<-which(apply(pValue_Array_InterpoledStineman, 1 , function (X) { sum(is.na(X))})==dim(pValue_Array_InterpoledStineman)[2])
pValue_Array_InterpoledStineman<-pValue_Array_InterpoledStineman[-temp,]
temp<-which(apply(pValueWilcox_Array_InterpoledStineman, 1 , function (X) { sum(is.na(X))})==dim(pValueWilcox_Array_InterpoledStineman)[2])
pValueWilcox_Array_InterpoledStineman<-pValueWilcox_Array_InterpoledStineman[-temp,]

temp<-which(apply(Medians_Array_InterpoledStineman, 1 , function (X) { sum(is.na(X))})==dim(Medians_Array_InterpoledStineman)[2])
Medians_Array_InterpoledStineman<-Medians_Array_InterpoledStineman[-temp,]
temp<-which(apply(Averages_Array_InterpoledStineman, 1 , function (X) { sum(is.na(X))})==dim(Averages_Array_InterpoledStineman)[2])
Averages_Array_InterpoledStineman<-Averages_Array_InterpoledStineman[-temp,]




LOG_pValue_Array<--log(pValue_Array)
LOG_pValue_Array_InterpoledLinear<--log(pValue_Array_InterpoledLinear)
LOG_pValue_Array_InterpoledSpline<--log(pValue_Array_InterpoledSpline)
LOG_pValue_Array_InterpoledStineman<--log(pValue_Array_InterpoledStineman)
LOG_pValueWilcox_Array<--log(pValueWilcox_Array)
LOG_pValueWilcox_Array_InterpoledLinear<--log(pValueWilcox_Array_InterpoledLinear)
LOG_pValueWilcox_Array_InterpoledSpline<--log(pValueWilcox_Array_InterpoledSpline)
LOG_pValueWilcox_Array_InterpoledStineman<--log(pValueWilcox_Array_InterpoledStineman)




#Print les heatmaps
png("Heatmap_AveragesEpilepsy.png", width=PngX, height=PngY, units="px")
heatmap( Averages_Array,Rowv = NA, Colv = NA,scale="none",col=Color_Ramp(200),cexCol=SizeHeatmapDays,cexRow=SizeHeatmapRows,main="Averages", xlab="days")
dev.off()
#aheatmap(cexRow =20,cexCol=20, Averages_Array,Colv = NA, Rowv = NA, main = "original",cellwidth = 20, cellheight = 5,legend=FALSE,color=couleur_BluePink_1000_V1)
png("Heatmap_MediansEpilepsy.png", width=PngX, height=PngY, units="px")
heatmap( Medians_Array,Rowv = NA, Colv = NA,scale="none",col=Color_Ramp(200),cexCol=SizeHeatmapDays,cexRow=SizeHeatmapRows,main="Medians", xlab="days")
dev.off()
png("Heatmap_pValues_Epilepsy.png", width=PngX, height=PngY, units="px")
heatmap( pValue_Array,Rowv = NA, Colv = NA,scale="none",col=Color_Ramp(200),cexCol=SizeHeatmapDays,cexRow=SizeHeatmapRows,main="pValue", xlab="days")
dev.off()
png("Heatmap_LOG_pValue_Epilepsy.png", width=PngX, height=PngY, units="px")
heatmap( LOG_pValue_Array,Rowv = NA, Colv = NA,scale="none",col=Color_Ramp(200),cexCol=SizeHeatmapDays,cexRow=SizeHeatmapRows,main="LOG_pValue", xlab="days")
dev.off()
png("Heatmap_pValuesWilcox_Epilepsy.png", width=PngX, height=PngY, units="px")
heatmap( pValueWilcox_Array,Rowv = NA, Colv = NA,scale="none",col=Color_Ramp(200),cexCol=SizeHeatmapDays,cexRow=SizeHeatmapRows,main="pValueWilcox", xlab="days")
dev.off()
png("Heatmap_LOG_pValueWilcox_Epilepsy.png", width=PngX, height=PngY, units="px")
heatmap( LOG_pValueWilcox_Array,Rowv = NA, Colv = NA,scale="none",col=Color_Ramp(200),cexCol=SizeHeatmapDays,cexRow=SizeHeatmapRows,main="LOG_pValueWilcox", xlab="days")
dev.off()
png("Heatmap_AveragesEpilepsy_linearInterpolation.png", width=PngX, height=PngY, units="px")
heatmap( Averages_Array_InterpoledLinear,Rowv = NA, Colv = NA,scale="none",col=Color_Ramp(200),cexCol=SizeHeatmapDays,cexRow=SizeHeatmapRows,main="Averages_InterpoledLinear", xlab="days")
dev.off()
png("Heatmap_MediansEpilepsy_linearInterpolation.png", width=PngX, height=PngY, units="px")
heatmap( Medians_Array_InterpoledLinear,Rowv = NA, Colv = NA,scale="none",col=Color_Ramp(200),cexCol=SizeHeatmapDays,cexRow=SizeHeatmapRows,main="Medians_InterpoledLinear", xlab="days")
dev.off()
png("Heatmap_pValues_Epilepsy_linearInterpolation.png", width=PngX, height=PngY, units="px")
heatmap( pValue_Array_InterpoledLinear,Rowv = NA, Colv = NA,scale="none",col=Color_Ramp(200),cexCol=SizeHeatmapDays,cexRow=SizeHeatmapRows,main="pValue_InterpoledLinear", xlab="days")
dev.off()
png("Heatmap_LOG_pValue_Epilepsy_linearInterpolation.png", width=PngX, height=PngY, units="px")
heatmap( LOG_pValue_Array_InterpoledLinear,Rowv = NA, Colv = NA,scale="none",col=Color_Ramp(200),cexCol=SizeHeatmapDays,cexRow=SizeHeatmapRows,main="LOG_pValue_InterpoledLinear", xlab="days")
dev.off()
png("Heatmap_pValuesWilcox_Epilepsy_linearInterpolation.png", width=PngX, height=PngY, units="px")
heatmap( pValueWilcox_Array_InterpoledLinear,Rowv = NA, Colv = NA,scale="none",col=Color_Ramp(200),cexCol=SizeHeatmapDays,cexRow=SizeHeatmapRows,main="pValueWilcox_InterpoledLinear", xlab="days")
dev.off()
png("Heatmap_LOG_pValueWilcox_Epilepsy_linearInterpolation.png", width=PngX, height=PngY, units="px")
heatmap( LOG_pValueWilcox_Array_InterpoledLinear,Rowv = NA, Colv = NA,scale="none",col=Color_Ramp(200),cexCol=SizeHeatmapDays,cexRow=SizeHeatmapRows,main="LOG_pValueWilcox_InterpoledLinear", xlab="days")
dev.off()
png("Heatmap_AveragesEpilepsy_SplineInterpolation.png", width=PngX, height=PngY, units="px")
heatmap( Averages_Array_InterpoledSpline,Rowv = NA, Colv = NA,scale="none",col=Color_Ramp(200),cexCol=SizeHeatmapDays,cexRow=SizeHeatmapRows,main="Averages_InterpoledSpline", xlab="days")
dev.off()
#aheatmap(cexRow =20,cexCol=20, Averages_Array,Colv = NA, Rowv = NA, main = "original",cellwidth = 20, cellheight = 5,legend=FALSE,color=couleur_BluePink_1000_V1)
png("Heatmap_MediansEpilepsy_SplineInterpolation.png", width=PngX, height=PngY, units="px")
heatmap( Medians_Array_InterpoledSpline,Rowv = NA, Colv = NA,scale="none",col=Color_Ramp(200),cexCol=SizeHeatmapDays,cexRow=SizeHeatmapRows,main="Medians_InterpoledSpline", xlab="days")
dev.off()
png("Heatmap_pValues_Epilepsy_SplineInterpolation.png", width=PngX, height=PngY, units="px")
heatmap( pValue_Array_InterpoledSpline,Rowv = NA, Colv = NA,scale="none",col=Color_Ramp(200),cexCol=SizeHeatmapDays,cexRow=SizeHeatmapRows,main="pValue_InterpoledSpline", xlab="days")
dev.off()
png("Heatmap_LOG_pValue_Epilepsy_SplineInterpolation.png", width=PngX, height=PngY, units="px")
heatmap( LOG_pValue_Array_InterpoledSpline,Rowv = NA, Colv = NA,scale="none",col=Color_Ramp(200),cexCol=SizeHeatmapDays,cexRow=SizeHeatmapRows,main="LOG_pValue_InterpoledSpline", xlab="days")
dev.off()
png("Heatmap_pValuesWilcox_Epilepsy_SplineInterpolation.png", width=PngX, height=PngY, units="px")
heatmap( pValueWilcox_Array_InterpoledSpline,Rowv = NA, Colv = NA,scale="none",col=Color_Ramp(200),cexCol=SizeHeatmapDays,cexRow=SizeHeatmapRows,main="pValueWilcox_InterpoledSpline", xlab="days")
dev.off()
png("Heatmap_LOG_pValueWilcox_Epilepsy_SplineInterpolation.png", width=PngX, height=PngY, units="px")
heatmap( LOG_pValueWilcox_Array_InterpoledSpline,Rowv = NA, Colv = NA,scale="none",col=Color_Ramp(200),cexCol=SizeHeatmapDays,cexRow=SizeHeatmapRows,main="LOG_pValueWilcox_InterpoledSpline", xlab="days")
dev.off()
png("Heatmap_AveragesEpilepsy_StinemanInterpolation.png", width=PngX, height=PngY, units="px")
heatmap( Averages_Array_InterpoledStineman,Rowv = NA, Colv = NA,scale="none",col=Color_Ramp(200),cexCol=SizeHeatmapDays,cexRow=SizeHeatmapRows,main="Averages_InterpoledStineman", xlab="days")
dev.off()
#aheatmap(cexRow =20,cexCol=20, Averages_Array,Colv = NA, Rowv = NA, main = "original",cellwidth = 20, cellheight = 5,legend=FALSE,color=couleur_BluePink_1000_V1)
png("Heatmap_MediansEpilepsy_StinemanInterpolation.png", width=PngX, height=PngY, units="px")
heatmap( Medians_Array_InterpoledStineman,Rowv = NA, Colv = NA,scale="none",col=Color_Ramp(200),cexCol=SizeHeatmapDays,cexRow=SizeHeatmapRows,main="Medians_InterpoledStineman", xlab="days")
dev.off()
png("Heatmap_pValues_Epilepsy_StinemanInterpolation.png", width=PngX, height=PngY, units="px")
heatmap( pValue_Array_InterpoledStineman,Rowv = NA, Colv = NA,scale="none",col=Color_Ramp(200),cexCol=SizeHeatmapDays,cexRow=SizeHeatmapRows,main="pValue_InterpoledStineman", xlab="days")
dev.off()
png("Heatmap_LOG_pValue_Epilepsy_StinemanInterpolation.png", width=PngX, height=PngY, units="px")
heatmap( LOG_pValue_Array_InterpoledStineman,Rowv = NA, Colv = NA,scale="none",col=Color_Ramp(200),cexCol=SizeHeatmapDays,cexRow=SizeHeatmapRows,main="LOG_pValue_InterpoledStineman", xlab="days")
dev.off()
png("Heatmap_pValuesWilcox_Epilepsy_StinemanInterpolation.png", width=PngX, height=PngY, units="px")
heatmap( pValueWilcox_Array_InterpoledStineman,Rowv = NA, Colv = NA,scale="none",col=Color_Ramp(200),cexCol=SizeHeatmapDays,cexRow=SizeHeatmapRows,main="pValueWilcox_InterpoledStineman", xlab="days")
dev.off()
png("Heatmap_LOG_pValueWilcox_Epilepsy_StinemanInterpolation.png", width=PngX, height=PngY, units="px")
heatmap( LOG_pValueWilcox_Array_InterpoledStineman,Rowv = NA, Colv = NA,scale="none",col=Color_Ramp(200),cexCol=SizeHeatmapDays,cexRow=SizeHeatmapRows,main="LOG_pValueWilcox_InterpoledStineman", xlab="days")
dev.off()






LOG_pValue_Array<-rbind(1:max(Input_L_Raw[,4]),LOG_pValue_Array)
row.names(LOG_pValue_Array)[1]<-"DATE"
LOG_pValue_Array<-cbind(row.names(LOG_pValue_Array),LOG_pValue_Array)
write.table(LOG_pValue_Array,"LOG_pValue_Array.tabtxt",col.names = FALSE, row.names = FALSE, sep = "\t")
LOG_pValue_Array<-LOG_pValue_Array[,-1]

pValue_Array<-rbind(1:max(Input_L_Raw[,4]),pValue_Array)
row.names(pValue_Array)[1]<-"DATE"
pValue_Array<-cbind(row.names(pValue_Array),pValue_Array)
write.table(pValue_Array,"pValue_Array.tabtxt",col.names = FALSE, row.names = FALSE, sep = "\t")
pValue_Array<-pValue_Array[,-1]

LOG_pValueWilcox_Array<-rbind(1:max(Input_L_Raw[,4]),LOG_pValueWilcox_Array)
row.names(LOG_pValueWilcox_Array)[1]<-"DATE"
LOG_pValueWilcox_Array<-cbind(row.names(LOG_pValueWilcox_Array),LOG_pValueWilcox_Array)
write.table(LOG_pValueWilcox_Array,"LOG_pValueWilcox_Array.tabtxt",col.names = FALSE, row.names = FALSE, sep = "\t")
LOG_pValueWilcox_Array<-LOG_pValueWilcox_Array[,-1]

pValueWilcox_Array<-rbind(1:max(Input_L_Raw[,4]),pValueWilcox_Array)
row.names(pValueWilcox_Array)[1]<-"DATE"
pValueWilcox_Array<-cbind(row.names(pValueWilcox_Array),pValueWilcox_Array)
write.table(pValueWilcox_Array,"pValueWilcox_Array.tabtxt",col.names = FALSE, row.names = FALSE, sep = "\t")
pValueWilcox_Array<-pValueWilcox_Array[,-1]

Averages_Array<-rbind(1:max(Input_L_Raw[,4]),Averages_Array)
row.names(Averages_Array)[1]<-"DATE"
Averages_Array<-cbind(row.names(Averages_Array),Averages_Array)
write.table(Averages_Array,"Averages_Array_ExpNDIFF.tabtxt",col.names = FALSE, row.names = FALSE, sep = "\t")
Averages_Array<-Averages_Array[,-1]

Medians_Array<-rbind(1:max(Input_L_Raw[,4]),Medians_Array)
row.names(Medians_Array)[1]<-"DATE"
Medians_Array<-cbind(row.names(Medians_Array),Medians_Array)
write.table(Medians_Array,"Medians_Array_ExpNDIFF.tabtxt",col.names = FALSE, row.names = FALSE, sep = "\t")
Medians_Array<-Medians_Array[,-1]




LOG_pValue_Array_InterpoledLinear<-rbind(1:max(Input_L_Raw[,4]),LOG_pValue_Array_InterpoledLinear)
row.names(LOG_pValue_Array_InterpoledLinear)[1]<-"DATE"
LOG_pValue_Array_InterpoledLinear<-cbind(row.names(LOG_pValue_Array_InterpoledLinear),LOG_pValue_Array_InterpoledLinear)
write.table(LOG_pValue_Array_InterpoledLinear,"LOG_pValue_Array_InterpoledLinear.tabtxt",col.names = FALSE, row.names = FALSE, sep = "\t")
LOG_pValue_Array_InterpoledLinear<-LOG_pValue_Array_InterpoledLinear[,-1]

pValue_Array_InterpoledLinear<-rbind(1:max(Input_L_Raw[,4]),pValue_Array_InterpoledLinear)
row.names(pValue_Array_InterpoledLinear)[1]<-"DATE"
pValue_Array_InterpoledLinear<-cbind(row.names(pValue_Array_InterpoledLinear),pValue_Array_InterpoledLinear)
write.table(pValue_Array_InterpoledLinear,"pValue_Array_InterpoledLinear.tabtxt",col.names = FALSE, row.names = FALSE, sep = "\t")
pValue_Array_InterpoledLinear<-pValue_Array_InterpoledLinear[,-1]

LOG_pValueWilcox_Array_InterpoledLinear<-rbind(1:max(Input_L_Raw[,4]),LOG_pValueWilcox_Array_InterpoledLinear)
row.names(LOG_pValueWilcox_Array_InterpoledLinear)[1]<-"DATE"
LOG_pValueWilcox_Array_InterpoledLinear<-cbind(row.names(LOG_pValueWilcox_Array_InterpoledLinear),LOG_pValueWilcox_Array_InterpoledLinear)
write.table(LOG_pValueWilcox_Array_InterpoledLinear,"LOG_pValueWilcox_Array_InterpoledLinear.tabtxt",col.names = FALSE, row.names = FALSE, sep = "\t")
LOG_pValueWilcox_Array_InterpoledLinear<-LOG_pValueWilcox_Array_InterpoledLinear[,-1]

pValueWilcox_Array_InterpoledLinear<-rbind(1:max(Input_L_Raw[,4]),pValueWilcox_Array_InterpoledLinear)
row.names(pValueWilcox_Array_InterpoledLinear)[1]<-"DATE"
pValueWilcox_Array_InterpoledLinear<-cbind(row.names(pValueWilcox_Array_InterpoledLinear),pValueWilcox_Array_InterpoledLinear)
write.table(pValueWilcox_Array_InterpoledLinear,"pValueWilcox_Array_InterpoledLinear.tabtxt",col.names = FALSE, row.names = FALSE, sep = "\t")
pValueWilcox_Array_InterpoledLinear<-pValueWilcox_Array_InterpoledLinear[,-1]

Averages_Array_InterpoledLinear<-rbind(1:max(Input_L_Raw[,4]),Averages_Array_InterpoledLinear)
row.names(Averages_Array_InterpoledLinear)[1]<-"DATE"
Averages_Array_InterpoledLinear<-cbind(row.names(Averages_Array_InterpoledLinear),Averages_Array_InterpoledLinear)
write.table(Averages_Array_InterpoledLinear,"Averages_Array_InterpoledLinear_ExpNDIFF.tabtxt",col.names = FALSE, row.names = FALSE, sep = "\t")
Averages_Array_InterpoledLinear<-Averages_Array_InterpoledLinear[,-1]

Medians_Array_InterpoledLinear<-rbind(1:max(Input_L_Raw[,4]),Medians_Array_InterpoledLinear)
row.names(Medians_Array_InterpoledLinear)[1]<-"DATE"
Medians_Array_InterpoledLinear<-cbind(row.names(Medians_Array_InterpoledLinear),Medians_Array_InterpoledLinear)
write.table(Medians_Array_InterpoledLinear,"Medians_Array_InterpoledLinear_ExpNDIFF.tabtxt",col.names = FALSE, row.names = FALSE, sep = "\t")
Medians_Array_InterpoledLinear<-Medians_Array_InterpoledLinear[,-1]





LOG_pValue_Array_InterpoledSpline<-rbind(1:max(Input_L_Raw[,4]),LOG_pValue_Array_InterpoledSpline)
row.names(LOG_pValue_Array_InterpoledSpline)[1]<-"DATE"
LOG_pValue_Array_InterpoledSpline<-cbind(row.names(LOG_pValue_Array_InterpoledSpline),LOG_pValue_Array_InterpoledSpline)
write.table(LOG_pValue_Array_InterpoledSpline,"LOG_pValue_Array_InterpoledSpline.tabtxt",col.names = FALSE, row.names = FALSE, sep = "\t")
LOG_pValue_Array_InterpoledSpline<-LOG_pValue_Array_InterpoledSpline[,-1]

pValue_Array_InterpoledSpline<-rbind(1:max(Input_L_Raw[,4]),pValue_Array_InterpoledSpline)
row.names(pValue_Array_InterpoledSpline)[1]<-"DATE"
pValue_Array_InterpoledSpline<-cbind(row.names(pValue_Array_InterpoledSpline),pValue_Array_InterpoledSpline)
write.table(pValue_Array_InterpoledSpline,"pValue_Array_InterpoledSpline.tabtxt",col.names = FALSE, row.names = FALSE, sep = "\t")
pValue_Array_InterpoledSpline<-pValue_Array_InterpoledSpline[,-1]

LOG_pValueWilcox_Array_InterpoledSpline<-rbind(1:max(Input_L_Raw[,4]),LOG_pValueWilcox_Array_InterpoledSpline)
row.names(LOG_pValueWilcox_Array_InterpoledSpline)[1]<-"DATE"
LOG_pValueWilcox_Array_InterpoledSpline<-cbind(row.names(LOG_pValueWilcox_Array_InterpoledSpline),LOG_pValueWilcox_Array_InterpoledSpline)
write.table(LOG_pValueWilcox_Array_InterpoledSpline,"LOG_pValueWilcox_Array_InterpoledSpline.tabtxt",col.names = FALSE, row.names = FALSE, sep = "\t")
LOG_pValueWilcox_Array_InterpoledSpline<-LOG_pValueWilcox_Array_InterpoledSpline[,-1]

pValueWilcox_Array_InterpoledSpline<-rbind(1:max(Input_L_Raw[,4]),pValueWilcox_Array_InterpoledSpline)
row.names(pValueWilcox_Array_InterpoledSpline)[1]<-"DATE"
pValueWilcox_Array_InterpoledSpline<-cbind(row.names(pValueWilcox_Array_InterpoledSpline),pValueWilcox_Array_InterpoledSpline)
write.table(pValueWilcox_Array_InterpoledSpline,"pValueWilcox_Array_InterpoledSpline.tabtxt",col.names = FALSE, row.names = FALSE, sep = "\t")
pValueWilcox_Array_InterpoledSpline<-pValueWilcox_Array_InterpoledSpline[,-1]

Averages_Array_InterpoledSpline<-rbind(1:max(Input_L_Raw[,4]),Averages_Array_InterpoledSpline)
row.names(Averages_Array_InterpoledSpline)[1]<-"DATE"
Averages_Array_InterpoledSpline<-cbind(row.names(Averages_Array_InterpoledSpline),Averages_Array_InterpoledSpline)
write.table(Averages_Array_InterpoledSpline,"Averages_Array_InterpoledSpline_ExpNDIFF.tabtxt",col.names = FALSE, row.names = FALSE, sep = "\t")
Averages_Array_InterpoledSpline<-Averages_Array_InterpoledSpline[,-1]

Medians_Array_InterpoledSpline<-rbind(1:max(Input_L_Raw[,4]),Medians_Array_InterpoledSpline)
row.names(Medians_Array_InterpoledSpline)[1]<-"DATE"
Medians_Array_InterpoledSpline<-cbind(row.names(Medians_Array_InterpoledSpline),Medians_Array_InterpoledSpline)
write.table(Medians_Array_InterpoledSpline,"Medians_Array_InterpoledSpline_ExpNDIFF.tabtxt",col.names = FALSE, row.names = FALSE, sep = "\t")
Medians_Array_InterpoledSpline<-Medians_Array_InterpoledSpline[,-1]








LOG_pValue_Array_InterpoledStineman<-rbind(1:max(Input_L_Raw[,4]),LOG_pValue_Array_InterpoledStineman)
row.names(LOG_pValue_Array_InterpoledStineman)[1]<-"DATE"
LOG_pValue_Array_InterpoledStineman<-cbind(row.names(LOG_pValue_Array_InterpoledStineman),LOG_pValue_Array_InterpoledStineman)
write.table(LOG_pValue_Array_InterpoledStineman,"LOG_pValue_Array_InterpoledStineman.tabtxt",col.names = FALSE, row.names = FALSE, sep = "\t")
LOG_pValue_Array_InterpoledStineman<-LOG_pValue_Array_InterpoledStineman[,-1]

pValue_Array_InterpoledStineman<-rbind(1:max(Input_L_Raw[,4]),pValue_Array_InterpoledStineman)
row.names(pValue_Array_InterpoledStineman)[1]<-"DATE"
pValue_Array_InterpoledStineman<-cbind(row.names(pValue_Array_InterpoledStineman),pValue_Array_InterpoledStineman)
write.table(pValue_Array_InterpoledStineman,"pValue_Array_InterpoledStineman.tabtxt",col.names = FALSE, row.names = FALSE, sep = "\t")
pValue_Array_InterpoledStineman<-pValue_Array_InterpoledStineman[,-1]

LOG_pValueWilcox_Array_InterpoledStineman<-rbind(1:max(Input_L_Raw[,4]),LOG_pValueWilcox_Array_InterpoledStineman)
row.names(LOG_pValueWilcox_Array_InterpoledStineman)[1]<-"DATE"
LOG_pValueWilcox_Array_InterpoledStineman<-cbind(row.names(LOG_pValueWilcox_Array_InterpoledStineman),LOG_pValueWilcox_Array_InterpoledStineman)
write.table(LOG_pValueWilcox_Array_InterpoledStineman,"LOG_pValueWilcox_Array_InterpoledStineman.tabtxt",col.names = FALSE, row.names = FALSE, sep = "\t")
LOG_pValueWilcox_Array_InterpoledStineman<-LOG_pValueWilcox_Array_InterpoledStineman[,-1]

pValueWilcox_Array_InterpoledStineman<-rbind(1:max(Input_L_Raw[,4]),pValueWilcox_Array_InterpoledStineman)
row.names(pValueWilcox_Array_InterpoledStineman)[1]<-"DATE"
pValueWilcox_Array_InterpoledStineman<-cbind(row.names(pValueWilcox_Array_InterpoledStineman),pValueWilcox_Array_InterpoledStineman)
write.table(pValueWilcox_Array_InterpoledStineman,"pValueWilcox_Array_InterpoledStineman.tabtxt",col.names = FALSE, row.names = FALSE, sep = "\t")
pValueWilcox_Array_InterpoledStineman<-pValueWilcox_Array_InterpoledStineman[,-1]

Averages_Array_InterpoledStineman<-rbind(1:max(Input_L_Raw[,4]),Averages_Array_InterpoledStineman)
row.names(Averages_Array_InterpoledStineman)[1]<-"DATE"
Averages_Array_InterpoledStineman<-cbind(row.names(Averages_Array_InterpoledStineman),Averages_Array_InterpoledStineman)
write.table(Averages_Array_InterpoledStineman,"Averages_Array_InterpoledStineman_ExpNDIFF.tabtxt",col.names = FALSE, row.names = FALSE, sep = "\t")
Averages_Array_InterpoledStineman<-Averages_Array_InterpoledStineman[,-1]

Medians_Array_InterpoledStineman<-rbind(1:max(Input_L_Raw[,4]),Medians_Array_InterpoledStineman)
row.names(Medians_Array_InterpoledStineman)[1]<-"DATE"
Medians_Array_InterpoledStineman<-cbind(row.names(Medians_Array_InterpoledStineman),Medians_Array_InterpoledStineman)
write.table(Medians_Array_InterpoledStineman,"Medians_Array_InterpoledStineman_ExpNDIFF.tabtxt",col.names = FALSE, row.names = FALSE, sep = "\t")
Medians_Array_InterpoledStineman<-Medians_Array_InterpoledStineman[,-1]










































print("End Vertical to Horizontal list then pValues")
}
#endregion#





if(!IdentifyEpilepsyBias)
{

      #region#orange   "timeWindow" 
Input_L_Raw[, 3] <- as.numeric(Input_L_Raw[, 3])
Input_L_Raw[, 4] <- as.numeric(Input_L_Raw[, 4])
Input_L_Raw <- Input_L_Raw[order(Input_L_Raw[, 4]), ]
Time_delta <- 1 + max(Input_L_Raw[, 4]) - min(Input_L_Raw[, 4])
rownames(Input_L_Raw) <- seq(1:(dim(Input_L_Raw)[1]))
Input_L_Raw <- cbind(Input_L_Raw, Input_L_Raw[, 4])
temp_verre <- 0

temp_k <- seq(1:Time_delta) %% (TimeWindow)
temp_k <- c(1,temp_k)
temp_k[length(temp_k)]<-0
temp_k <- which(temp_k == 0)

    for (i in 1:(ceil(Time_delta/TimeWindow)))   #1:length(temp_K)
    {
       
       if(length(which(Input_L_Raw[, 5] < 10000000 ))<MinimumProfilLength){ Input_L_Raw[which(Input_L_Raw[, 5] < 10000000 ), 5]<-    10000000 + i ;  break}
     
        temp1 <- max(which(Input_L_Raw[, 5] < (temp_k[i])))
        if (abs(temp1)>length(Input_L_Raw[,5])) {
           temp1<-length(Input_L_Raw[,5])
        }
     
        Input_L_Raw[, 5][temp_verre:temp1] <- 10000000 + i
        temp_verre <- temp1 + 1
    }
colnames(Input_L_Raw)[5] <- paste("Time_windows_", TimeWindow, "days", sep = "")
Input_L_Raw[, 5] <- Input_L_Raw[, 5] - 10000000
Input_L_Raw <- split(Input_L_Raw, Input_L_Raw[, 5])
print("END TIMEWINDOW")
#endregion#

#region#cyan    Use function1 pour chaque "TimeWindow"
for (h in 1:length(Input_L_Raw))
{
    Inject_H <- Input_L_Raw[[h]][, -5]
    Profils_export_L[[h]] <- Function1(Inject_H, TimeBining, TimeShift, MinimumProfilLength, MinimumQuantityOfPatientsPerProfil, DateOrigine, Correl_Thresold,h)
    print(paste(h, "_", length(Input_L_Raw), sep = ""))
}#endregion#


print("Exporting profils")
if (max(as.numeric(lapply(Profils_export_L,length))) == 0) {  stop("*********** CANCELLED No Profils To Export ***********") }

for (i in 1:length(Profils_export_L)) {  Profils_export_Array <- bind_rows(Profils_export_Array, ldply(Profils_export_L[[i]], data.frame)) }



#region#pink Analyzis days in function of correlation (normalized DIFF )  SameDayAnalyzis_B
print("average and NormDiff of the profiles" )

if(SameDayAnalyzis_B)
{

    Profils_export_Array[,8:dim(Profils_export_Array)[2]]<-apply(Profils_export_Array[,8:dim(Profils_export_Array)[2]],2,as.numeric)

for(window in 1:TimeWindow )
{
print(paste("Window=",window,"/",TimeWindow))



temp<-which(Profils_export_Array[,1]==paste("window=",window,sep=""))
temp<-Profils_export_Array[temp,]
temp_Profil_patientS_pairS<-temp[,c(-1,-c(4:7))]
temp_Profil_patientS_pair<-temp_Profil_patientS_pairS
temp_pairs_levels<-levels(as.factor(temp_Profil_patientS_pairS[,2]))
#endregion#
print("Graphs")
#region#pink Plots
if (length(temp_pairs_levels)!=0) 
{
for (pair_i in 1:length(temp_pairs_levels))
{
temp<-which(temp_Profil_patientS_pairS[,2]==temp_pairs_levels[pair_i])
temp_Profil_patientS_pair<-temp_Profil_patientS_pairS[temp,]
#if there is the same patient, take the minimum for the same patient(e.g. because of +2), why same patient and same pair?
#minimum for the same patient
#
#
temp_plot_patientS_pair<-data.frame(matrix(NA,nrow=2*(dim(temp_Profil_patientS_pair)[1])/3,ncol=dim(temp_Profil_patientS_pair)[2]-1))
temp_patients_levels<-levels(as.factor(temp_Profil_patientS_pair[,1]))
colnames(temp_plot_patientS_pair)[1]<-temp_pairs_levels[pair_i]
for (patient_i in 1:(length(temp_patients_levels) ))
{
temp_plot_patientS_pair[2*patient_i-1,2:(dim(temp_plot_patientS_pair)[2])]<-temp_Profil_patientS_pair[((patient_i*3)-2),3:(dim(temp_Profil_patientS_pair)[2])]
temp_plot_patientS_pair[2*patient_i,2:(dim(temp_plot_patientS_pair)[2])]<-abs(apply(temp_Profil_patientS_pair[((patient_i*3)-1):(patient_i*3),3:(dim(temp_Profil_patientS_pair)[2])],2,diff))
temp_plot_patientS_pair[2*patient_i,1]<-temp_patients_levels[patient_i]
temp_plot_patientS_pair[2*patient_i-1,1]<-paste("Date Of ",temp_patients_levels[patient_i],sep="")
}

par(new=FALSE)
png(filename=paste(temp_pairs_levels[pair_i],".png"),width=1920, height=1080,units="px",)


for (indice_patient in 1: ((dim(temp_plot_patientS_pair)[1])/2)) 
{
par(new=TRUE)
temp<-as.numeric(temp_plot_patientS_pair[indice_patient*2-1,-1])
temp1<-as.numeric(temp_plot_patientS_pair[indice_patient*2,-1])
plot(x=temp,y=temp1,type='l', main=temp_pairs_levels[pair_i], xlab="Date",ylab="NDiff")
temp<-sub(x=temp_plot_patientS_pair[indice_patient*2,1],pattern ="Patient=",replacement="")
text(x=temp_plot_patientS_pair[indice_patient*2-1,ncol(temp_plot_patientS_pair)],y=temp_plot_patientS_pair[indice_patient*2,ncol(temp_plot_patientS_pair)],labels=temp,pos=4)
}
dev.off()
}}}}
#endregion#
################################


#or ( i id.vars
#cat("\n",Nom_Etude,"_",as.name(eval(EffectToStudy)),"_",": test du gene n ",i,"  Name: ",as.character( ArrayMaster[p+1,1]),"\n")
#)




#region#green  Export to file DataCorData  and Profils



# Score In Function Of Epilepsy : Part 1 create references Patient → EpilecpticScore
if (ScoreInFunctionOfEpilepsy_B)            #FOR NOW NEEDS TO BE ALWAYS TRUE
{
print("Score In Function Of Epilepsy Status")

#Epilectic_Enrichement<-ScoreInFunctionOfEpilepsy_F()

temp<-which(Input_L_Raw_Qualitatif[,2]=="EPILEPTICSTATUS")
WeightPatient_Epilepsy<-Input_L_Raw_Qualitatif[temp,]


WeightPatient_Epilepsy<-as.data.frame(cbind(WeightPatient_Epilepsy[,1],WeightPatient_Epilepsy[,3]))

if (class(WeightPatient_Epilepsy[1,2])=="character")
{
WeightPatient_Epilepsy[,2]<-substr(WeightPatient_Epilepsy[,2],1,2)
if(  !(sum(!grepl("\\D", WeightPatient_Epilepsy[,2]) )==length(WeightPatient_Epilepsy[,2])))
{

WeightPatient_Epilepsy[,2]<-substr(WeightPatient_Epilepsy[,2],1,1)
}
}
WeightPatient_Epilepsy[,2]<-as.numeric(WeightPatient_Epilepsy[,2])

EPILEPTICSTATUS_AverageTotal<-round(mean(WeightPatient_Epilepsy[,2]),2)
EPILEPTICSTATUS_SDPopulation<-round(sd(WeightPatient_Epilepsy[,2]),2)

print(paste("EPILEPTICSTATUS: n=",length(WeightPatient_Epilepsy[,2]),"mean=",EPILEPTICSTATUS_AverageTotal,"SD=",EPILEPTICSTATUS_SDPopulation))
}



Profils_export_Array<-cbind(Profils_export_Array[,1],Profils_export_Array)
temp<- Profils_export_Array[,3:4]



temp<-cbind(temp,temp[,1])






# attach raw epileptic weight  normalized epileptic weight to Input_L_Raw, total epileptic weight
if(ScoreInFunctionOfEpilepsy_B)
{
for (indice_patient in 1:nrow(WeightPatient_Epilepsy))
{
    print(paste("Replace",WeightPatient_Epilepsy[indice_patient ,1],"by",WeightPatient_Epilepsy[indice_patient ,2]))
temp[,3]<-str_replace(temp[,3],WeightPatient_Epilepsy[indice_patient ,1],as.character(WeightPatient_Epilepsy[indice_patient ,2]))

#  USE  str_replace_all




}
colnames(temp)[3]<-c("EpilepticScore_perPatient")

print("Wait")

}

Profils_export_Array<-cbind(Profils_export_Array,temp[,3])
colnames(Profils_export_Array)[ncol(Profils_export_Array)]<-c("EpilepticScore_perPatient")
temp[,1]<-as.factor(temp[,1])
temp[,2]<-as.factor(temp[,2])







    for (i in 1:length(levels(temp[,2])) )
{
temp2<-which(temp[,2]==levels(temp[,2])[i])
temp1<-length(levels(factor(temp[temp2,1])))
Profils_export_Array[temp2,2]<-temp1
}
    temp <- which(Profils_export_Array[, 2] < MinimumQuantityOfPatientsPerProfil)
    if (length(temp) > 0)
    {
    Profils_export_Array <- Profils_export_Array[-temp, ]
    }

    if (dim(Profils_export_Array)[1] == 0) 
    {
    stop("Not Enough Patients per Profils")
    }
        Profils_export_Array[is.na(Profils_export_Array)] <- ""
        Profils_export_Array[,6]<-round(as.numeric(Profils_export_Array[,6]),2)
        Data_Cor_Data <- cbind(Profils_export_Array[, 4:7], Profils_export_Array[, c(3,2)],Profils_export_Array[, ncol(Profils_export_Array)])
        temp <- seq(1, dim(Data_Cor_Data)[1], by = 3)
        Data_Cor_Data <- Data_Cor_Data[temp, ]
         Data_Cor_Data <-cbind( Data_Cor_Data , 0)
        colnames(Data_Cor_Data)<- c("Pair","Data1", "PearsonCorrelation", "Data2", "Patient", "QofPatientsWithThisRelation","EpilepticScore_perPatient","NormalizedEpilepticScore_perPair")
        levels_factors<-levels(as.factor(Data_Cor_Data[,1]))
Data_Cor_Data[,7]<-as.numeric(Data_Cor_Data[,7])
        for (indice_pair in 1:length(levels_factors))
        {
            temp<-which(Data_Cor_Data[,1]==levels_factors[indice_pair])

temp1<-mean(Data_Cor_Data[temp,7])/EPILEPTICSTATUS_AverageTotal
Data_Cor_Data[temp,8]<-temp1
        }
temp<-which(Data_Cor_Data[,8]<1)
Data_Cor_Data[temp,8]<--1/Data_Cor_Data[temp,8]
Data_Cor_Data[,8]<-round(Data_Cor_Data[,8],2)




print("Writting files . . . ")

        



        
        
        
        
        Data_Cor_Data <- rbind(Data_Cor_Data[1, ], Data_Cor_Data)
        Data_Cor_Data[1, ] <- colnames(Data_Cor_Data)
        temp1<-paste("cor",Correl_Thresold,"_min",MinimumProfilLength,"_Pts",MinimumQuantityOfPatientsPerProfil,"_bin",TimeBining,"_Shft",TimeShift,"_W",TimeWindow,sep="")
        write.table(Data_Cor_Data, paste("R_",temp1,".tabtxt",sep=""), col.names = FALSE, row.names = FALSE, sep = "\t")
        Profils_export_Array <- Profils_export_Array[, c(-5, -7)]
Profils_export_Array<-cbind(Profils_export_Array[,1:3],Profils_export_Array[,ncol(Profils_export_Array)],Profils_export_Array[,4:(ncol(Profils_export_Array)-1)])

        Profils_export_Array <- rbind(Profils_export_Array[1, ], Profils_export_Array)
        Profils_export_Array[1, ] <- "Data"
        Profils_export_Array[1, 1:6] <- c("Window", "QofPatientsWithThisRelation","Patient","EpilepticStatusPerPatient", "Pairs of correlations", "Correlation", "Name of Data")
        write.table(Profils_export_Array, paste("R_Profil_",temp1,".tabtxt",sep="") , col.names = FALSE, row.names = FALSE, sep = "\t")
        Profils_export_Array <- Profils_export_Array[-1, ]
    #endregion#
#region#yellow "Adding Patient labels"

if (ExportPatientLabels)
{
print("Adding Patient labels")
Profils_export_Array_PtNames<-Profils_export_Array[,c(1:4)]
Profils_export_Array_PtNames<-Profils_export_Array_PtNames[,-2]
Profils_export_Array_PtNames<-cbind(paste(Profils_export_Array_PtNames[,3],Profils_export_Array_PtNames[,1],sep="|"),Profils_export_Array_PtNames)
seq(1,dim(Profils_export_Array_PtNames)[1],by=3)
Profils_export_Array_PtNames<-Profils_export_Array_PtNames[seq(1,dim(Profils_export_Array_PtNames)[1],by=3),]
Profils_export_Array_PtNames<-Profils_export_Array_PtNames[,c(-2,-4)]<-Profils_export_Array_PtNames[,c(-2,-4)]
Profils_export_Array_PtNames<-Profils_export_Array_PtNames[order(Profils_export_Array_PtNames[,1]),]
temp_L<-levels(as.factor(Profils_export_Array_PtNames[,1]))
Export_PtNames<-(temp_L);Export_PtNames<-as.data.frame(Export_PtNames)
for (indice_FactorWindow in 1:length(temp_L))
{
    print(paste(indice_FactorWindow,"/",length(temp_L)))
temp<-which(Profils_export_Array_PtNames[,1]==temp_L[indice_FactorWindow])
temp1<-Profils_export_Array_PtNames[temp,2]
Export_PtNames[indice_FactorWindow,2]<-length(temp)
Export_PtNames[indice_FactorWindow,3:(length(temp1)+2)]<-temp1



}
Export_PtNames[is.na(Export_PtNames)]<-""
 write.table(Export_PtNames, paste("R_PatientLabels.tabtxt",sep="") , col.names = FALSE, row.names = FALSE, sep = "\t")
}


print("Files writting finished")
#endregion#
}
