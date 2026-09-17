#  Date start at 1 not 0
# Put everything upletters
# Input.tabtxt OR InputForValidation.tabtxt
# REMOVE THE NAs before Input???
# Option to keep results across patients only if they are close to each others in a locked time mode

#1) Compute pvalue coulumn in function of days and ABS correl     P==T.DIST.2T(|COR|*SQRT(N-2)/SQRT(1-COR^2),N-2)      Correct les "#DIV/0!" either accept or remove perfect correlation (favorise longueur profil instead of short perfect profil?)
#2) Cut at desired pValue, Separate negativew correlation from positive correaltion if mutliprocessor add all files in multiple worksheets of 1 file with Asap Utilities
 #Order pvalue & Cortype PAtient... to identify the smalest pvalue per window for each patient #variable
 #then multiple consolidation range with Pivot Table across multiple tabs with ALT D P. (if needed #else straight to pivot)
#Put the column to create row-Pivot on the left (ex: concatenate Patient and pair of variable to #have the average across the different signeficant windows) First do inside patients to average on windows then do the average without patient to have the real count

#3) Separate column 'pair of correlation on _|_ then Reorder columns for DATA1 Interraction Data2 so more easy with cytoscape
#
#
#

#The Score_Name=  COLOR is used to give a color (score_Value) to patients
#Last Column:  The Data_type QUALITATIF_NOTEMPOREL  is used for non temporel and qualitatif data , Score_Name = Color, EpilepticStatus
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
library(roll)
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
library(tidyr)
library(zoo)

#endregion#

#region#green Parameters
setwd("P:\\Biostat\\Multivariate\\October\\relaxed\\Mitch_ALL_OLD")
MinimumProfilLength <- 5    # miniumum profil length for correlation analyzis
MaximumProfilLength <- 10  # maximum profil length for correlation analyzis
MinimumPvalueCorrelation <- 0.01
MinimumQuantityOfPatientsPerProfil <- 5
ParralelComputing=TRUE   # If true concatenate results from all parraleles results
ProcessorE.C.= 12
TotalQuantityOfProcessorAvaillable= 12
Correl_Thresold <- 0.7    # min5 cor0.9 pvalue=0.04     | min7 cor0.75  pvalue=0.05
DateOrigine <- "2000-1-1"
DateFormat <- FALSE # if dateformat is true transform the date after DateOrigine, else keeps numerical: 1,2,3,4

ActivateKendall <- FALSE # Not used yet
DataNormalization <- FALSE
Nom_Interraction <- "Validation"
CreateValidationData <- FALSE     #if True need InputForValidation.tabtxt in the wide format (with time as the first row), this create the correct file to be used in excel to creat the final Input.tabtxt (Then put the Epileptic variable for each patient using "Qualitatif_NoTemporel" and the data EPILEPTICSTATUS ) 
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


Profils_export_Array <- data.frame()
options(stringsAsFactors = FALSE)
if (IdentifyEpilepsyBias) {DataNormalization = TRUE;MinimumProfilLength <- 1;MinimumQuantityOfPatientsPerProfil <- 1 }
#endregion#
print("START")

#region#blue  : Inputation
Input_Raw <- read.table("Input.tabtxt", sep = "\t", header = FALSE, check.names = FALSE)
Input_Raw<-apply(Input_Raw,2,toupper)

# Verify units are all the same for each score_Name, cancel everything if not the same units. Remove Units if they are okay
# LOOSELY IMPLEMENTED
colnames(Input_Raw) <- c("PATIENT", "SCORE_NAME", "SCORE_VALUE", "SCORE_UNIT", "DATE","Data Type")
print("Verify Adequation")
print(Input_Raw[1, ])
Input_Raw <- Input_Raw[-1, ]

# Separate Qualitatif from Quantitative
temp<-which(Input_Raw[,6]=="QUALITATIF_NOTEMPOREL")
Input_Raw_Qualitatif<-Input_Raw[temp,]
if (length(temp) !=0) {Input_Raw<-Input_Raw[-temp,]}
Input_Raw_Qualitatif<-as.data.frame(Input_Raw_Qualitatif)

#endregion#
#region#green
Input_Raw <- as.data.frame(Input_Raw )
Input_Raw [,3]<-as.numeric(Input_Raw [,3])
Input_Raw [,5]<-as.numeric(Input_Raw [,5])

#endregion#

#region#lightblue  Remove si pas assez de data points per patients per analyzis
print("Remove si pas assez de data points per patients per analyzis")
Input_Raw<-cbind(Input_Raw,paste(Input_Raw[,1],Input_Raw[,2]))
#temp<-add_count(Input_Raw,Input_Raw[,5])
Input_Raw<-as.data.frame(Input_Raw)
Input_Raw[,3]<-as.numeric(Input_Raw[,3])
Input_Raw[,5]<-as.numeric(Input_Raw[,5])

temp<- ave(Input_Raw[,ncol(Input_Raw)],Input_Raw[,ncol(Input_Raw)], FUN=length)

Input_Raw<-cbind(Input_Raw,temp)
Input_Raw[,ncol(Input_Raw)]<-as.numeric(Input_Raw[,ncol(Input_Raw)])
temp<-which(Input_Raw[,ncol(Input_Raw)]<MinimumProfilLength)

print(paste("Removing",length(temp),"data with less than",MinimumProfilLength,"Points", "from total of",dim(Input_Raw)[1] ) )



if(length(temp)!=0){Input_Raw<-Input_Raw[-temp,]}
Input_Raw<-Input_Raw[,-ncol(Input_Raw<-Input_Raw)]
Input_Raw<-Input_Raw[,-ncol(Input_Raw<-Input_Raw)]
#endregion#

#region#blue Fill the Emptyto0    # I have faster scripts in version V519 of multivariate only
if(EMPTYTO0_B)
{
temp<-which(Input_Raw[,6]=="EMPTYTO0")

if (length(temp)>=1)
{
Input_Raw_EmptyTo0_Pts_Analyzes<-Input_Raw[temp,]
Patients<-levels(as.factor(Input_Raw[,1]))
Input_Raw<-Input_Raw[-temp,]
Levels_To0<-levels(as.factor(Input_Raw_EmptyTo0_Pts_Analyzes[,2]))
for (indice_analyzeTo0 in 1:length(Levels_To0))
{
print(paste("EmptyTo0 for:",Levels_analyzeTo0[indice_analyzeTo0]))
Input_Raw_EmptyTo0_Pts_Analyze1<-Input_Raw_EmptyTo0_Pts_Analyzes[which(Input_Raw_EmptyTo0_Pts_Analyzes[,2]==Levels_analyzeOK[indice_analyzeOK]),]
temp_patientLevelsOK<-levels(as.factor(Input_Raw_EmptyTo0_Pts_Analyze1[,1]))
for (indice_patientLevelsOK in 1:length(temp_patientLevelsOK))
{
Input_Raw_EmptyTo0_1Pt_Analyze1<-Input_Raw_EmptyTo0_Pts_Analyze1[which(Input_Raw_EmptyTo0_Pts_Analyze1[,1]==temp_patientLevelsOK[indice_patientLevelsOK]),]   
temp1<-min(Input_Raw_EmptyTo0_1Pt_Analyze1[,5])
if(temp1>1)
{
temp3<-bind_rows(replicate(temp1-1, Input_Raw_EmptyTo0_1Pt_Analyze1[1,], simplify = FALSE))
temp3[,3]<-0
temp3[,5]<-c(1:(temp1-1))
Input_Raw<-rbind(Input_Raw, temp3)
}
}
}

temp_MaxDate<-max(Input_Raw_EmptyTo0_Pts_Analyzes[,5])
patientLevelsOK<-levels(as.factor(Input_Raw_EmptyTo0_Pts_Analyzes[,1]))
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
names(temp)<-names(Input_Raw )
Input_Raw<-rbind(Input_Raw, temp)
}
}

#endregion#
#region#blue merge analyze with units, remove unitsInput_Raw[,2]<-paste(Input_Raw[,2],"_",Input_Raw[,4],sep="")
Input_Raw <- Input_Raw[, -4]
#endregion#

#region#red
if (ParralelComputing)
{

Input_Raw<-Input_Raw[order(Input_Raw[,1]),]
temp<-levels(as.factor(Input_Raw[,1]))
temp1<-length(temp)
temp1<-temp1/TotalQuantityOfProcessorAvaillable
temp1<-split(temp, ceiling(seq_along(temp)/temp1))
temp1<-temp1[[ProcessorE.C.]]
temp1<-which(Input_Raw[,1] %in% temp1)
Input_Raw<-Input_Raw[temp1,]

}

#endregion#
#region#green DataNormalization
        if(DataNormalization)
        {
levels_factors<-levels(as.factor(Input_Raw[,2]))
for (Analyze_indice in 1:(length(levels_factors)))
{
    temp<-which(Input_Raw[,2]==levels_factors[Analyze_indice])
    temp1<-Input_Raw[temp,3]
    temp_sd <- sd(temp1, na.rm = TRUE) 
    temp_average <- mean(temp1, na.rm = TRUE) 
    Input_Raw[temp,3] <- (temp1-temp_average )/temp_sd
    
        }
        }
        
      #endregion#

#region#blue Vertical to Horizontal
Input_Raw<-Input_Raw[,-ncol(Input_Raw)] # Enleve type of variables because useless information

Max_Days<-max(Input_Raw[,4],na.rm = T)

#Complete les donnees manquantes et passe de vertical a horyzontal
Input_L_Complete<- as.data.frame(complete(Input_Raw,PATIENT,SCORE_NAME,DATE))  
print("Reshaping....")
Input_A<-reshape(Input_L_Complete,direction='wide',idvar=c("PATIENT","SCORE_NAME"),timevar="DATE")


      #endregion#
#region#green interpolation
Input_A_Interpoled<-t(Input_A)
Input_A_Interpoled<-as.data.frame(Input_A_Interpoled)

Patient_List<-levels(as.factor(as.character(Input_A_Interpoled[1,])))
Variable_List<-levels(as.factor(as.character(Input_A_Interpoled[2,])))
Variable_Quantity <- length(Variable_List)
Patient_Quantity <- length(Patient_List)
Day_Quantity<-dim(Input_A_Interpoled)[1]-2

Input_A_Interpoled_Matrix<-Input_A_Interpoled[3:nrow(Input_A_Interpoled),]
Input_A_Interpoled_Matrix<-apply(Input_A_Interpoled_Matrix,2,as.numeric)

Input_A_Interpoled_Matrix<-apply(Input_A_Interpoled_Matrix,2,function(X) { tryCatch ( { na_interpolation(X,maxgap=Interpolation_maxgap_inDays,option="stine")}, error=function(e) {rep(NA,Day_Quantity)} )})

Input_A_Interpoled[3:nrow(Input_A_Interpoled),]<-Input_A_Interpoled_Matrix

colnames(Input_A_Interpoled_Matrix)<-Input_A_Interpoled[2,]


      #endregion#
#region#red Correlation

ccor <- function(x) { cc <- cor(x); cc[lower.tri(cc)] }
paste_ <- function(...) paste(..., sep = "_|_")

Result_Correlation_Vertical<-data.frame(matrix(NA,1,6))      
Result_Correlation_Vertical<-Result_Correlation_Vertical[-1,]

for (indice_patient in 1:Patient_Quantity)
{
print(paste("Patient:",Patient_List[indice_patient],"  ",indice_patient," on ",Patient_Quantity,sep=""))
Input_A_Interpoled_Matrix_PerPatient<-Input_A_Interpoled_Matrix[  ,which(Input_A_Interpoled[1,]==Patient_List[indice_patient])  ]

Result_Correlation_Horyzontal_CorMax_PerPatient_PerWindows<-data.frame(matrix(NA,1,2+(Variable_Quantity^2-Variable_Quantity)/2)) 
Result_Correlation_Horyzontal_CorMax_PerPatient_PerWindows<-Result_Correlation_Horyzontal_CorMax_PerPatient_PerWindows[-1,]
Result_Correlation_Horyzontal_CorMax_Location_PerPatient_PerWindows<-Result_Correlation_Horyzontal_CorMax_PerPatient_PerWindows

for (indice_CorrelationWindow in MinimumProfilLength:MaximumProfilLength)
{
print(paste("Correlation Window analyzing: ",indice_CorrelationWindow," on ", MaximumProfilLength," days",sep=""))
temp_correlation_1 <- rollapplyr(Input_A_Interpoled_Matrix_PerPatient, width=indice_CorrelationWindow , ccor, fill = NA, by.column = FALSE) #0.02
temp_correlation_1[is.na(temp_correlation_1)]<-0

temp_correlation_1_Max_Location<-t(apply(temp_correlation_1,2,function(X){which.max(abs(X))}))
temp_correlation_1_Max_Location<-as.vector(temp_correlation_1_Max_Location)
temp_correlation_1_Max<-temp_correlation_1[cbind(temp_correlation_1_Max_Location,1:dim(temp_correlation_1)[2])]

temp<-c(Patient_List[indice_patient],indice_CorrelationWindow)

Result_Correlation_Horyzontal_CorMax_PerPatient_PerWindows<-rbind(Result_Correlation_Horyzontal_CorMax_PerPatient_PerWindows,c(temp,temp_correlation_1_Max))
Result_Correlation_Horyzontal_CorMax_Location_PerPatient_PerWindows<-rbind(Result_Correlation_Horyzontal_CorMax_Location_PerPatient_PerWindows,c(temp,temp_correlation_1_Max_Location))

}
if (!all(Result_Correlation_Horyzontal_CorMax_PerPatient_PerWindows[,-c(1,2)]==0))
{

names_mat <- do.call("outer", list(colnames(Input_A_Interpoled_Matrix_PerPatient), colnames(Input_A_Interpoled_Matrix_PerPatient), paste_))

colnames(Result_Correlation_Horyzontal_CorMax_PerPatient_PerWindows) <- c("Patient","CorrelationWindowLength",names_mat[lower.tri(names_mat)] )
colnames(Result_Correlation_Horyzontal_CorMax_Location_PerPatient_PerWindows) <- c("Patient","CorrelationWindowLength",names_mat[lower.tri(names_mat)] ) 

temp<-apply(Result_Correlation_Horyzontal_CorMax_PerPatient_PerWindows[,-1],2,function(X){all(X==0)})
temp<-which(temp); temp<-temp+1
Result_Correlation_Horyzontal_CorMax_PerPatient_PerWindows<-Result_Correlation_Horyzontal_CorMax_PerPatient_PerWindows[,-temp]
Result_Correlation_Horyzontal_CorMax_Location_PerPatient_PerWindows<-Result_Correlation_Horyzontal_CorMax_Location_PerPatient_PerWindows[,-temp]

Result_Correlation_Horyzontal_CorMax_PerPatient_PerWindows[,2]<-as.factor(Result_Correlation_Horyzontal_CorMax_PerPatient_PerWindows[,2])
temp_CorMax<-melt(Result_Correlation_Horyzontal_CorMax_PerPatient_PerWindows,id.vars=c("Patient","CorrelationWindowLength"))
temp_Location<-melt(Result_Correlation_Horyzontal_CorMax_Location_PerPatient_PerWindows,id.vars=c("Patient","CorrelationWindowLength"))
temp_CorMax[,4]<-as.numeric(temp_CorMax[,4])
temp_Location[,2]<-as.numeric(temp_Location[,2])
temp_Location[,4]<-as.numeric(temp_Location[,4])
temp_CorMax<-cbind(temp_CorMax,temp_Location[,4]-temp_Location[,2]+1,temp_Location[,4])

Result_Correlation_Vertical<-rbind(Result_Correlation_Vertical,temp_CorMax)
#colnames(Result_Correlation_Vertical)[4:6]<-c("Cor_Max","CorrelationPatternBegin","CorrelationPatternEnd" )

temp<-which(abs(Result_Correlation_Vertical[,4])<Correl_Thresold)
if (length(temp)!=0){Result_Correlation_Vertical<-Result_Correlation_Vertical[-temp,]}
}}
colnames(Result_Correlation_Vertical)<-c("Patient","CorrelationLength","Variable1_|_Variable2","CorrelationMax","CorrelationPatternBegin","CorrelationPatternEnd" )

if (ParralelComputing)
{

tag<-paste("_[P",ProcessorE.C.,"_On_",TotalQuantityOfProcessorAvaillable,"]",sep="")
colnames(Result_Correlation_Vertical)[1]<-paste(colnames(Result_Correlation_Vertical)[1],tag)
write.table(col.names=T,row.names=F,Result_Correlation_Vertical,file=paste("R_Result_Correlation_Vertical",tag,".tabtxt",sep=""),sep="\t")
}
if (!ParralelComputing)
{
write.table(col.names=T,row.names=F,Result_Correlation_Vertical,file="R_Result_Correlation_Vertical.tabtxt",sep="\t")
}
print("******************END****************************")
      #endregion#







