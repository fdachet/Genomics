 rm(list=ls(all=TRUE))

# WITH HEADER col1: Weight Col2:NameOf Cell   Col3: Name of gene  Col4: to end: Fluorescence Values
# PEARSON CORRELATION

# Only unique geneNames
library(FactoMineR);library(ggplot2);library(calibrate);library(audio); library(diptest);library(missMDA);library(pvclust); library(dplyr);library(Hmisc)
library(mvoutlier);library(matrixStats)
#'install.packages("FactoMineR");install.packages("ggplot2");install.packages("calibrate");install.packages("audio"); install.packages("diptest");install.packages("missMDA");install.packages("pvclust"); install.packages("dplyr");install.packages("Hmisc")
#install.packages("mvoutlier");install.packages("matrixStats")
setwd("P:\\TEMP\\test")
options(stringsAsFactors = FALSE)
Input=read.table("Input.tabtxt", sep="\t",header=TRUE,check.names=FALSE)
Name_Study= "PartialTEST"

ImpactCorrelationOutliers=20    #How much of the profil correlation can be explained by the outliers (defaults 20%)
MinQuantityOfUPDrivingPatients=1   #e.g. If you remove this quantity of patients the profil is still significant     "..The profil need to be created by more than 1 patient.."   
ProfilMinSize=5    #Size minimal d un profil (e.x. = 5), sans compter les Driving patients
Representation=60     #percentage de la population qui va etre utiliser pour comparer et identifier les outliers  (standard quantill 0-25% 25%-50% 50-75% 75%-100%) = 50          Si pas assez d outliers ? reduce representation,  si trop d outliers increase representation
pval=   0.05   ;       #pval  for HC     
Police_Size= 1; ZoomForDisplay=1
Police_Size_Auto= TRUE
par(mar=c(2,2,2,1))
QuantityOfIterrationsForRandomness = 10000   #Quantity of random iteration used to include or exclude samples based on coef of variations  1E6 should be enough
pValueForRandommess = 0.05   #0.1 = this level of variation is only found in a maximum of 10% of random patients 
BootStrapeValues = 10000  #NPO : Desactivate Firewall before creating the parraleles nodes

Input<-Input[order(Input[,2],Input[,3]),]
Input_M<-as.matrix(Input[,-c(1,2,3)]);rownames(Input_M)<-Input[,3]
Weights<-as.numeric(Input[,1]);Weights[which(is.na(Weights))]=0
ListCellNames<-levels(as.factor(Input[,2]))
ListGeneNames<-Input[,3]
ListSamples<-colnames(Input[4:dim(Input)[2]]);QuantitySamples=length(ListSamples)

Output_MEDIANS=Input[1:length(ListCellNames),-c(1,2)]; colnames(Output_MEDIANS)[1]<-"CellNames";Output_MEDIANS[,1]<-"CellNames"
Output_MEDIANS[,2:dim(Output_MEDIANS)[2]]<-0

mainDir<-getwd()
if(min(c(apply(Input_M,1,function(X) {sd(X,na.rm = TRUE)}),apply(Input_M,2,function(X) {sd(X,na.rm = TRUE)})))==0){print("Problem Definition of Data, Problem SD");wait(2);quit(save="no")}
FlagProblemDomaineDeDefinition=FALSE
n_pt <- dim(Input)[2]-2
t_crit1t <- qt(pval, n_pt-2,lower.tail=FALSE)
t_crit2t <- qt(pval/2, n_pt-2,lower.tail=FALSE)
r_crit1t <- 1/sqrt(((n_pt-2)/t_crit1t^2)+1);
r_crit2t <- 1/sqrt(((n_pt-2)/t_crit2t^2)+1);
r_crit2t
Cor.limited.By.pvalue.1t <- r_crit1t
Cor.limited.By.pvalue.2t <- r_crit2t
Cor.limited.By.pvalue<-Cor.limited.By.pvalue.2t
Representation<-(100-Representation)/200
#Compute the Scaled 
Input.Scaled<-Input_M
temp_sd<-apply(Input.Scaled,1,function(X){sd(X, na.rm = TRUE)})

temp_mean<-rowMeans(Input.Scaled,na.rm=TRUE)
Input.Scaled<-Input.Scaled-temp_mean
Input.Scaled<-Input.Scaled/temp_sd
Input.Scaled_M<-Input.Scaled
Input.Scaled<-cbind(Input[,1:3],Input.Scaled)
Input.Scaled<-rbind(colnames(Input.Scaled),Input.Scaled)


Input.Scaled<-Input.Scaled[-1,]
Input.Scaled<-as.data.frame(Input.Scaled)
Input.Scaled[,4:dim( Input.Scaled)[2]]<-apply( Input.Scaled[,4:dim( Input.Scaled)[2]],2,as.numeric)
# Comput weighted median
Output_ScaledWeightedMedian <- array(0,c(length(ListCellNames),dim(Input_M)[2]))
for (i in 1 : length(ListCellNames))
{
print(ListCellNames[i])
temp1<-which(Input.Scaled[,2]==ListCellNames[i])
Input_EnCours<-Input.Scaled_M[temp1,]
Weight_EnCours<-Weights[temp1]; Weight_EnCours<-Weight_EnCours/mean(Weight_EnCours)
if(!is.null(dim(Input_EnCours))){Output_ScaledWeightedMedian[i,]<-apply(Input_EnCours,2,function(X) {weightedMedian(X,Weight_EnCours, na.rm = TRUE)}  )}

}
Output_ScaledWeightedMedian_M<-Output_ScaledWeightedMedian
Output_ScaledWeightedMedian<-rbind(colnames(Input_M),Output_ScaledWeightedMedian)
Output_ScaledWeightedMedian<-cbind(c("Cluster",ListCellNames),Output_ScaledWeightedMedian)

# Comput Scaled Weighted SD 
Output_ScaledWeightedSD<- array(0,c(length(ListCellNames),dim(Input_M)[2]))

for (i in 1 : length(ListCellNames))
{
print(ListCellNames[i])
temp1<-which(Input.Scaled[,2]==ListCellNames[i])
Input_EnCours<-Input.Scaled_M[temp1,]
Weight_EnCours<-Weights[temp1]; Weight_EnCours<-Weight_EnCours/mean(Weight_EnCours)
if(!is.null(dim(Input_EnCours))){Output_ScaledWeightedSD[i,]<-apply(Input_EnCours,2,function(X) {weightedSd (X,Weight_EnCours)}  )}

}

Output_ScaledWeightedSD_M<-Output_ScaledWeightedSD
Output_ScaledWeightedSD<-rbind(colnames(Input_M),Output_ScaledWeightedSD)
Output_ScaledWeightedSD<-cbind(c("Cluster",ListCellNames),Output_ScaledWeightedSD)


# Verify random fluctuation of the same length with multiple iterations Excluding the  MAX)

ThresoldVariationsClusters<-0*rep(1:length(ListCellNames))


for (i in 1: length(ListCellNames))
{
print(paste("Computing Weighted standard deviation for",ListCellNames[i] ,"with" ,QuantityOfIterrationsForRandomness , " iterations"))
temp1<-which(Input[,2]==ListCellNames[i])
Input_EnCours<-Input.Scaled_M[temp1,]
Weight_EnCours<-Weights[temp1]; Weight_EnCours<-Weight_EnCours/mean(Weight_EnCours)

Input_EnCours_forRandomness<-Input_EnCours
for (j in  0: (MinQuantityOfUPDrivingPatients-1))
{
if(j>0)
{
temp<-apply(abs(Input_EnCours_forRandomness),1,which.max)

for (k in 1:length(temp))
{
Input_EnCours_forRandomness[k,temp[k]]<-NA
}
}
}

if(!is.null(dim(Input_EnCours))){minRandomness <-apply(Input_EnCours_forRandomness,1,function(X) {min(X,na.rm=TRUE)}  )}
if(!is.null(dim(Input_EnCours))){maxRandomness <-apply(Input_EnCours_forRandomness,1,function(X) {max(X,na.rm=TRUE)}  )}
random.E.C.<-array(0,c(dim(Input_EnCours)[1], QuantityOfIterrationsForRandomness))
for (j in 1:((dim(Input_EnCours)[1])))
{
random.E.C.[j,]<-runif(QuantityOfIterrationsForRandomness ,minRandomness[j] ,maxRandomness[j] )
print(paste("iterations_randomness for data = ",j," /",dim(Input_EnCours)[1]))
}

random.sd<-apply(random.E.C.,2,function(X) {weightedSd (X,Weight_EnCours)} )
ThresoldVariationsClusters[i]<-random.sd[order(random.sd)]   [pValueForRandommess *QuantityOfIterrationsForRandomness]
}


Output_ScaledWeightedSD_PatientsAccepted<-Output_ScaledWeightedSD; Output_ScaledWeightedSD_PatientsAccepted[1,1]<-"Clusters"

for (i in 1: length(ListCellNames))
{
Output_ScaledWeightedSD_PatientsAccepted[i+1,]<-"REJECTED"
Output_ScaledWeightedSD_PatientsAccepted[i+1,which(Output_ScaledWeightedSD_M[i,]<=ThresoldVariationsClusters[i])+1]<-"ACCEPTED"
Output_ScaledWeightedSD_PatientsAccepted[i+1,1]<-ListCellNames[i]





}

#PUT THE REJECTED HIGH AS NON-TESTED for SD
for (i in 1: length(ListCellNames))
{

Median_Encours<-Output_ScaledWeightedMedian_M[i,]




for (j in  0: (MinQuantityOfUPDrivingPatients-1))
{
if(j>0)
{
temp<-which.max(abs(Median_Encours))
if(Output_ScaledWeightedSD_PatientsAccepted[i+1,temp+1]=="REJECTED"){Output_ScaledWeightedSD_PatientsAccepted[i+1,temp+1]<-"HIGH_NOT_TESTED"}
Median_Encours[temp]<-NA



}
}
}
# Analyse of the quantity of driving patients for each profil
ImpactCorrelationOutliers<-ImpactCorrelationOutliers/100

for (i in 1: length(ListCellNames))
{

# where are the ABS  High patients in profil of te median
MedianEnCours1<-Output_ScaledWeightedMedian_M[i,]
temp1<-which(Input.Scaled[,2]==ListCellNames[i])
Input.EnCours1<-Input.Scaled_M[temp1,]
Weight_EnCours<-Weights[temp1]; Weight_EnCours<-Weight_EnCours/mean(Weight_EnCours)


temp<-which(Output_ScaledWeightedSD_PatientsAccepted[i+1,]=="REJECTED")-1
if(dim(Input.Scaled_M)[2]-length(temp)-MinQuantityOfUPDrivingPatients<ProfilMinSize){Output_ScaledWeightedSD_PatientsAccepted[i+1,]<-"REJECTED"}
if(dim(Input.Scaled_M)[2]-length(temp)-MinQuantityOfUPDrivingPatients>=ProfilMinSize)
{
MedianEnCours1[temp]<-NA
Input.EnCours1[,temp]<-NA






for (j in 1 : (MinQuantityOfUPDrivingPatients -1))
{
if (j>0)
{
temp_high<-which.max(abs(MedianEnCours1))

MedianEnCoursWOhigh<-MedianEnCours1[-temp_high]
Input.EnCoursWOhigh<-Input.EnCours1[,- temp_high]
cor1<-mean(apply( Input.EnCours1,1,function(X){cor(X,MedianEnCours1,use="complete.obs")})*Weight_EnCours)
corWOhigh<-mean(apply( Input.EnCoursWOhigh,1,function(X){cor(X,MedianEnCoursWOhigh,use="complete.obs")})*Weight_EnCours)
temp_cor<-corWOhigh/cor1
if(temp_cor>(1-ImpactCorrelationOutliers)){Output_ScaledWeightedSD_PatientsAccepted[i+1,temp_high+1]<-"ACCEPTED"}
if(temp_cor<=(1-ImpactCorrelationOutliers)){Output_ScaledWeightedSD_PatientsAccepted[i+1,]<-"REJECTED"}
MedianEnCours1[temp_high]<-NA
Input.EnCours1[,temp_high]<-NA
}
}
}
}
# Give la median en percentage, only on the accepted
Output_ScaledWeightedMedian[,1]<-paste(Output_ScaledWeightedMedian[,1],"_Profil",sep="")
Output_ScaledWeightedSD_PatientsAccepted[,1]<-paste(Output_ScaledWeightedSD_PatientsAccepted[,1],"_Acceptance",sep="")
Output_ScaledWeightedSD[,1]<-paste(Output_ScaledWeightedSD[,1],"_WeightedSD",sep="")
Output_ResultsMixed<-rbind(Output_ScaledWeightedMedian,Output_ScaledWeightedSD_PatientsAccepted,Output_ScaledWeightedSD)

Output_ScaledWeightedMedian_percent_M<-Output_ScaledWeightedMedian_M
Output_ScaledWeightedMedian_percent<-Output_ScaledWeightedMedian_percent_M
#Only on  the ACCEPTED!!!
for (i in 1: length(ListCellNames))
{
Median_Encours<-Output_ScaledWeightedMedian_M[i,]
Temp_Rejected<-which(Output_ScaledWeightedSD_PatientsAccepted[i+1,]=="REJECTED")
Median_Encours[Temp_Rejected-1]<-NA




if(length(Output_ScaledWeightedMedian_M[i,])-length(which.na(Median_Encours))>=MinQuantityOfUPDrivingPatients+ProfilMinSize)
{


temp_min<-min(Median_Encours,na.rm=TRUE)
temp_max<-max(Median_Encours,na.rm=TRUE)




Output_ScaledWeightedMedian_percent_M[i,]<-Median_Encours-temp_min

 Output_ScaledWeightedMedian_percent_M[i,]<-Output_ScaledWeightedMedian_percent_M[i,]*100/(temp_max-temp_min)

Output_ScaledWeightedMedian_percent_M[i,]<-round(Output_ScaledWeightedMedian_percent_M[i,],0)


}
else {Output_ScaledWeightedMedian_percent_M[i,]<-NA}
}
Output_ScaledWeightedMedian_percent<-Output_ScaledWeightedMedian
temp1<-dim(Output_ScaledWeightedMedian_percent)[1];temp2<-dim(Output_ScaledWeightedMedian_percent)[2]
temp3<-paste(Output_ScaledWeightedMedian_percent_M,"%",sep="")
Output_ScaledWeightedMedian_percent[2:temp1,2:temp2]<-temp3
Output_ScaledWeightedMedian_percent[,1]<-paste(Output_ScaledWeightedMedian_percent[,1],"_Median(%)",sep="")
Output_ResultsMixed<-rbind(Output_ResultsMixed,Output_ScaledWeightedMedian_percent)
#Writing Files
write.table(Output_ResultsMixed,file=paste(Name_Study,sep="_",   "Profiles_Results.tabtxt"),sep="\t", col.names =FALSE, row.names =FALSE)
#write.table(Input.Scaled,file=paste(sep="",Name_Study,"_Scaled.tabtxt"),sep='\t',col.names=FALSE,row.names=FALSE)
# Do The plots

for (i in 1 : length(ListCellNames))
{
All_Reject=FALSE
print(ListCellNames[i])
setwd(mainDir)
dir.create(showWarnings=FALSE,ListCellNames[i])
setwd(paste(mainDir,"/",ListCellNames[i],sep=""))
temp1<-which(Input.Scaled[,2]==ListCellNames[i])

Weight_EnCours<-Weights[temp1]; Weight_EnCours<-Weight_EnCours/mean(Weight_EnCours)
Weight_EnCours_Normalized<-Weight_EnCours-min(Weight_EnCours, na.rm=TRUE)
Weight_EnCours_Normalized<-0.1+Weight_EnCours_Normalized/max(Weight_EnCours_Normalized, na.rm=TRUE)
if(anyNA(Weight_EnCours_Normalized)){Weight_EnCours_Normalized<-rep(0.5,length(temp1))}
png( paste(Name_Study,ListCellNames[i],"Original",".png", sep="_"),height= 1080*ZoomForDisplay, width = 1920*ZoomForDisplay)


Input_EnCours<-Input_M[temp1,]
temp_xMax=dim(Input_EnCours)[2];temp_yMax= max(Input_EnCours,na.rm=TRUE) ; temp_ymin=min(Input_EnCours,na.rm=TRUE)
par(lwd = 1)

par(new=FALSE)
Color_Wheel<-rainbow(dim(Input_EnCours)[1],start=0.2,end=0.7)
for (j in 1: dim(Input_EnCours)[1])
{
par(lwd = 4*Weight_EnCours_Normalized[j])
plot(Input_EnCours[j,],type="l",yaxt = "n", xaxt = "n",lty=1,col=Color_Wheel[j],xlim=c(1,temp_xMax), ylim=c(temp_ymin,temp_yMax))
par(new=TRUE)
}
par(lwd = 1)
axis(1, at=1:(dim(Input_EnCours)[2]),colnames(Input_EnCours),cex.axis=Police_Size)
title(main=list(paste(ListCellNames[i]," Original "),cex=Police_Size,col="black")    )
dev.off()
png( paste(Name_Study,ListCellNames[i],"ACCEPTED",".png", sep="_"),height= 1080*ZoomForDisplay, width = 1920*ZoomForDisplay)
par(lwd = 1)

Input_EnCours_LastMedianSD<-rbind(Input.Scaled_M[temp1,],Output_ScaledWeightedMedian_M[i,],Output_ScaledWeightedSD_M[i,])
patientsRejected<-which(Output_ScaledWeightedSD_PatientsAccepted[i+1,]=="REJECTED")-1



if (length(patientsRejected)== length(Output_ScaledWeightedSD_PatientsAccepted[i+1,])-1){All_Reject=TRUE}
if (!All_Reject)
{
if (length(patientsRejected)!=0) {Input_EnCours_LastMedianSD<-Input_EnCours_LastMedianSD[,-patientsRejected  ]}
}



Median.E.C.<-Input_EnCours_LastMedianSD[dim(Input_EnCours_LastMedianSD)[1]-1,]
SD.E.C.<-Input_EnCours_LastMedianSD[dim(Input_EnCours_LastMedianSD)[1],]
Input_EnCours<-Input_EnCours_LastMedianSD[1:(dim(Input_EnCours_LastMedianSD)[1]-2),]


temp_xMax=dim(Input_EnCours)[2];temp_yMax= max(Input_EnCours,na.rm=TRUE) ; temp_ymin=min(Input_EnCours,na.rm=TRUE)
par(new=FALSE)
Color_Wheel<-rainbow(dim(Input_EnCours)[1],start=0.2,end=0.7)
for (j in 1: dim(Input_EnCours)[1])
{
par(lwd = 4*Weight_EnCours_Normalized[j])
plot(Input_EnCours[j,],type="l",yaxt = "n", xaxt = "n",lty=1,col=Color_Wheel[j],xlim=c(1,temp_xMax), ylim=c(temp_ymin,temp_yMax))
par(new=TRUE)
}
par(lwd = 1)
axis(1, at=1:(dim(Input_EnCours)[2]),colnames(Input_EnCours),cex.axis=Police_Size)
if (All_Reject==FALSE)
{
arrows(1:dim(Input_EnCours)[2],Median.E.C. - SD.E.C.,1:dim(Input_EnCours)[2],Median.E.C. + SD.E.C., code=3, length=0.04, angle = 90,col="black")
par(lwd = 2)

lines(Median.E.C.)
par(lwd = 1)


title(main=list(paste(ListCellNames[i]," ProfilAccepted at p=",pValueForRandommess),cex=Police_Size,col="black"))    
}
if (All_Reject==TRUE)
{
title(main=list(paste(ListCellNames[i]," × × ×××× ALL Profil Rejected at p<",pValueForRandommess," ×××× × ×"),cex=Police_Size,col="darkred"))    
}
dev.off()
if (All_Reject==FALSE)
{

png( paste(Name_Study,ListCellNames[i],"Accepted&Rejected",".png", sep="_"),height= 1080*ZoomForDisplay, width = 1920*ZoomForDisplay)
par(lwd = 1)
Input_EnCours_LastMedianSD<-rbind(Input.Scaled_M[temp1,],Output_ScaledWeightedMedian_M[i,],Output_ScaledWeightedSD_M[i,])

Input_EnCours_LastMedianSD<-Input_EnCours_LastMedianSD[,order(Output_ScaledWeightedSD_M[i,])]

Median.E.C.<-Input_EnCours_LastMedianSD[dim(Input_EnCours_LastMedianSD)[1]-1,]
SD.E.C.<-Input_EnCours_LastMedianSD[dim(Input_EnCours_LastMedianSD)[1],]
Input_EnCours<-Input_EnCours_LastMedianSD[1:(dim(Input_EnCours_LastMedianSD)[1]-2),]


temp_xMax=dim(Input_EnCours)[2];temp_yMax= max(Input_EnCours,na.rm=TRUE) ; temp_ymin=min(Input_EnCours,na.rm=TRUE)
par(new=FALSE)
Color_Wheel<-rainbow(dim(Input_EnCours)[1],start=0.2,end=0.7)
for (j in 1: dim(Input_EnCours)[1])
{
par(lwd = 4*Weight_EnCours_Normalized[j])
plot(Input_EnCours[j,],type="l",yaxt = "n", xaxt = "n",lty=1,col=Color_Wheel[j],xlim=c(1,temp_xMax), ylim=c(temp_ymin,temp_yMax))
par(new=TRUE)
}
par(lwd = 1)

axis(1, at=1:(dim(Input_EnCours)[2]),colnames(Input_EnCours),cex.axis=Police_Size)



#temp<-which
QPTsRejected<-length(which(Output_ScaledWeightedSD_PatientsAccepted[i+1,-1]=="REJECTED"))
QPTsAccepted<-length(Median.E.C.)-QPTsRejected
if (QPTsRejected!=0&QPTsAccepted!=0){Temp_text<-    list(paste(ListCellNames[i]," ProfilAccepted(Blue), Rejected(Red) at p=",pValueForRandommess,"Ordered by SD"))    }
if (QPTsRejected==0){Temp_text<-   (paste(ListCellNames[i]," All Profil Accepted at p=",pValueForRandommess,"Ordered by SD"))    }
if (QPTsAccepted==0){Temp_text<-  (paste(ListCellNames[i]," × × ×××× All profils are Rejected(Red) at p=",pValueForRandommess,"×××× × ×"))    }

title(Temp_text,cex=Police_Size,col="black")
Max_Height<-max(Input_EnCours)
Min_Height<-min(Input_EnCours)
if (QPTsAccepted!=0){rect(0,Min_Height,QPTsAccepted+0.1,Max_Height,,border="blue")}
if (QPTsRejected!=0){rect(QPTsAccepted+0.2,Min_Height,QPTsAccepted+QPTsRejected,Max_Height,border="red")}
par(lwd = 1)




arrows(1:QPTsAccepted,Median.E.C.[1:QPTsAccepted] - SD.E.C.[1:QPTsAccepted],1:QPTsAccepted,Median.E.C.[1:QPTsAccepted] + SD.E.C.[1:QPTsAccepted], code=3, length=0.04, angle = 90,col="black")
par(lwd = 2)
lines(Median.E.C.[1:QPTsAccepted])
par(lwd = 1)

dev.off()
}
}




# END PLOTS
# Plot the HCs

temp<-rowSums(t(apply(Output_ScaledWeightedSD_PatientsAccepted[-1,-1],1,function(X){X=="ACCEPTED"})))
temp<-length(temp[temp>=ProfilMinSize])
if((length(ListCellNames)>2)&(temp>=3))
{
setwd(mainDir)
dir.create(showWarnings=FALSE,"HC")
setwd(paste(mainDir,"/","HC",sep=""))
#png(paste(Name_Study, "HC+_average.png", sep="_"),height= 1080*ZoomForDisplay, width = 1920*ZoomForDisplay)

Output_ScaledWeightedMedian_Accepted<-Output_ScaledWeightedMedian

Output_ScaledWeightedMedian_Accepted[which(Output_ScaledWeightedSD_PatientsAccepted=="REJECTED")]<-NA

rownames(Output_ScaledWeightedMedian_Accepted)<-Output_ScaledWeightedMedian_Accepted[,1]
colnames(Output_ScaledWeightedMedian_Accepted)<-Output_ScaledWeightedMedian_Accepted[1,]
Output_ScaledWeightedMedian_Accepted_M<-Output_ScaledWeightedMedian_Accepted[-1,-1]
Output_ScaledWeightedMedian_Accepted_M<-apply(Output_ScaledWeightedMedian_Accepted_M,2,'as.numeric')
rownames(Output_ScaledWeightedMedian_Accepted_M)<-rownames(Output_ScaledWeightedMedian_Accepted)[-1]
temp<-rowSums(t(apply(Output_ScaledWeightedMedian_Accepted_M,1,"is.na")))
temp<-which(temp>(dim(Output_ScaledWeightedMedian_Accepted_M)[2]-ProfilMinSize  ))
Output_ScaledWeightedMedian_Accepted_M_E.C.<-Output_ScaledWeightedMedian_Accepted_M[-temp,]
png(paste(Name_Study, "HC+_PearsonAverage.png", sep="_"),height= 1080*ZoomForDisplay, width = 1920*ZoomForDisplay)
 plot(pvclust(t(Output_ScaledWeightedMedian_Accepted_M_E.C.),method.dist="cor",   method.hclust="average", use.cor="pairwise.complete.obs",nboot=BootStrapeValues ,parallel=TRUE))
dev.off()





png(paste(Name_Study, "HC-_average.png", sep="_"),height= 1080*ZoomForDisplay, width = 1920*ZoomForDisplay)


temp1<-cor(t(Output_ScaledWeightedMedian_Accepted_M_E.C.),use="pairwise.complete.obs")
 temp1[is.na(temp1)]<-0

temp2<-which(temp1>-Cor.limited.By.pvalue)


temp1[temp2]<-0
temp<-(as.dist(1-abs(temp1)))
temp3<-as.dendrogram(hclust(temp,"average"))
plot(temp3, horiz=TRUE,,main="",cex=Police_Size)

if(length(temp1)!=length(temp2))
{
title(main=list(paste("Corel-_Average_LimitedByPvalue",Name_Study,"ProblemDefinition=",FlagProblemDomaineDeDefinition),cex=Police_Size,col="red"))
try(segments(x0=1-Cor.limited.By.pvalue, y0=0,x1=1-Cor.limited.By.pvalue,y1=1200,col="red"))
try(text(1-Cor.limited.By.pvalue+0.1,0.2,paste (sep="","xzxzPvalue=",pval, "  Corr=",round(Cor.limited.By.pvalue,2)), col="red",cex=1  ))
} else

{
title(main=list(paste("No Negative Correlation found",Name_Study),cex=Police_Size,col="red"))
}
dev.off()
}
